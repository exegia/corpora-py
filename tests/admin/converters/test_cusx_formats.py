"""Synthetic source fidelity, PDF extraction limits and public API regression."""

import json
import posixpath
import zipfile
from pathlib import Path

import pymupdf
import pytest
from admin.converters.cusx import convert_to_cusx, digest, validate_cusx_archive
from admin.parsers.epub_structure import unit_text, walk
from admin.parsers.schema import Document, SourceFormat
from corpora_linking import (
    CatalogEntry,
    SnapshotCatalog,
    SnapshotResolver,
    TextLocator,
    TextSnapshot,
)
from lxml import etree

HEBREW = "וְחַטָּאִ֑ים"
PLAIN = f" \tGreek ἄνθρωπος; {HEBREW}.\r\n\r\n  e\u0301 😀\u00a0end.\r\n "
MARKDOWN = f"""# One

A **strong** and *emphasized* {HEBREW}, é 😀 and {chr(96)}code{chr(96)}.

## Nested

- item one
- item two

| Name | Value |
| --- | --- |
| Greek | ἄνθρωπος |

[source](https://example.org) ![diagram](diagram.png)

~~~python
# code, not a chapter
  print("é")
~~~
"""
TEI = f"""<?xml version="1.0"?><TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="edition" xml:lang="he">
<teiHeader><fileDesc><titleStmt><title>Edition</title><author>Alice</author></titleStmt></fileDesc></teiHeader>
<text><body>
<div type="chapter" xml:id="one"><head>One</head><p> Hebrew <hi rend="bold">{HEBREW}</hi> é.</p>
<div type="section"><head>Nested</head><note xml:id="note">Note 😀</note></div></div>
<div type="chapter" xml:id="two"><head>Two</head><p><ref target="#note">back</ref></p><graphic url="diagram.png"/></div>
</body></text></TEI>"""
XML = f'<catalog xmlns="urn:example" xmlns:e="urn:extra" e:version="2"> Before <chapter id="one">{HEBREW} é</chapter> between <chapter id="two">😀</chapter> after </catalog>'
PDF = Path(__file__).parents[1] / "fixtures/cusx/outlined.pdf"


def contents(package):
    with zipfile.ZipFile(package) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    trees = [Document.model_validate_json(members[d["tree"]]) for d in manifest["documents"]]
    snapshots = [
        TextSnapshot.model_validate_json(members[d["snapshot"]]) for d in manifest["documents"]
    ]
    return members, manifest, trees, snapshots


@pytest.mark.parametrize(
    "fmt,text",
    [
        (SourceFormat.PLAIN, PLAIN),
        (SourceFormat.MARKDOWN, MARKDOWN),
        (SourceFormat.XML, XML),
        (SourceFormat.TEI, TEI),
    ],
)
def test_source_stream_structure_assets_and_pinned_selection(tmp_path, fmt, text):
    source = tmp_path / ("source." + fmt.value)
    source.write_bytes(text.encode())
    (tmp_path / "diagram.png").write_bytes(b"synthetic asset")
    package = convert_to_cusx(source, tmp_path / "book.cusx", source_format=fmt, name="Book")
    assert validate_cusx_archive(package)["valid"]
    members, manifest, trees, snapshots = contents(package)
    assert members[manifest["source"]["evidence"]] == source.read_bytes()
    expected = (
        "".join(etree.fromstring(text.encode()).itertext())
        if fmt in (SourceFormat.XML, SourceFormat.TEI)
        else text
    )
    assert "".join(s.text for s in snapshots) == expected
    assert "".join(unit_text(u) for t in trees for u in t.units) == expected
    snapshot = next(s for s in snapshots if HEBREW in s.text)
    start = snapshot.text.index(HEBREW)
    locator = TextLocator(
        stream_id=snapshot.stream_id, start=start, end=start + len(HEBREW), exact=HEBREW
    )
    request = snapshot.endpoint.model_copy(update={"locators": (locator,)})
    resolver = SnapshotResolver(
        catalog=SnapshotCatalog(entries=(CatalogEntry(work_id=request.work_id, names=("Book",)),)),
        snapshots=tuple(snapshots),
    )
    assert resolver.resolve(request).status == "resolved"
    assert (
        resolver.resolve(request.model_copy(update={"revision": "sha256:" + "0" * 64})).status
        != "resolved"
    )
    nodes = [n for t in trees for u in t.units for n in walk(u)]
    if fmt == SourceFormat.MARKDOWN:
        assert len(trees) == 1
        assert {
            "section",
            "heading",
            "paragraph",
            "bullet_list",
            "list_item",
            "table",
            "strong",
            "em",
            "link",
            "image",
            "code_inline",
            "fence",
        } <= {n.type for n in nodes}
        assert [n.attrs["level"] for n in nodes if n.type == "section"] == ["1", "2"]
        assert members["assets/diagram.png"] == b"synthetic asset"
    elif fmt == SourceFormat.TEI:
        assert [e["role"] for e in manifest["documents"]] == ["front_matter", "chapter", "chapter"]
        assert any(n.type == "head" and unit_text(n) == "One" for n in nodes)
        assert any(n.type == "note" and n.attrs["xml:id"] == "note" for n in nodes)
        back = next(n for n in nodes if n.type == "ref")
        assert back.source_attrs["target"] == "#note" and back.attrs["target"] == "0002.usx#note"
        assert members["assets/diagram.png"] == b"synthetic asset"
    elif fmt == SourceFormat.XML:
        assert len(trees) == 1 and trees[0].units[0].type == "catalog"
        assert trees[0].units[0].namespace == "urn:example"
        assert trees[0].units[0].attrs["e:version"] == "2"
    else:
        assert len(trees) == 1


def test_real_pdf_pages_outlines_images_unicode_and_original_bytes(tmp_path, pinned_pdf_ocr):
    package = convert_to_cusx(
        PDF, tmp_path / "book.cusx", source_format=SourceFormat.PDF, name="PDF"
    )
    members, manifest, trees, snapshots = contents(package)
    assert validate_cusx_archive(package)["valid"]
    assert len(trees) == 2
    assert all("Unicode café" in s.text for s in snapshots)
    assert json.loads(members["assets/pdf/ocr/provenance.json"])["packages"]["docling"] == "2.137.0"
    assert members[manifest["source"]["evidence"]] == PDF.read_bytes()
    assert [e["source"]["page_number"] for e in manifest["documents"]] == [1, 2]
    marks = manifest["navigation"]["bookmarks"]
    assert [e["label"] for e in marks] == ["Chapter 1", "Chapter 2"]
    assert marks[0]["children"][0]["target"] == marks[0]["target"]
    assert marks[1]["target"]["document_id"] == manifest["documents"][1]["id"]
    image = next(n for n in walk(trees[0].units[0]) if n.type == "image")
    resolved = posixpath.normpath(posixpath.join("documents", image.attrs["src"]))
    assert resolved in members
    assert not any("Unresolved source resource" in d for d in manifest["diagnostics"])
    assert any(n.attrs.get("provenance") for n in walk(trees[0].units[0]))
    assert any("source fidelity requires" in d for d in manifest["diagnostics"])


@pytest.mark.parametrize(
    "kind,message",
    [
        ("encrypted", "Encrypted PDF"),
        ("broken", "PDF could not be read"),
    ],
)
def test_unreadable_or_partial_pdf_never_produces_a_package(tmp_path, kind, message):
    source = tmp_path / "source.pdf"
    if kind in ("blank", "partial", "partial_dense"):
        import io

        from PIL import Image

        png = io.BytesIO()
        Image.new("RGB", (400, 500), "white").save(png, format="PNG")
        with pymupdf.open() as document:
            page = document.new_page(width=400, height=500)
            page.insert_image(page.rect, stream=png.getvalue())
            if kind == "partial_dense":
                page.insert_textbox(page.rect, "Substantial native text alongside a scan. " * 40)
            elif kind == "partial":
                page.insert_text((20, 30), "Only a header was extracted")
            document.save(source)
    elif kind == "encrypted":
        with pymupdf.open(PDF) as document:
            document.save(
                source, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret"
            )
    else:
        source.write_bytes(b"%PDF-1.4 unreadable input")
    output = tmp_path / "book.cusx"
    with pytest.raises(ValueError, match=message):
        convert_to_cusx(source, output, source_format=SourceFormat.PDF, name="Book")
    assert not output.exists()


@pytest.mark.parametrize(
    "fmt,text,error",
    [
        (SourceFormat.XML, "<root><unclosed>", "XML"),
        (SourceFormat.TEI, "<catalog>words</catalog>", "TEI input requires"),
        (
            SourceFormat.XML,
            '<root xml:base="media/"><graphic url="fig.png"/></root>',
            "base resolution",
        ),
        (
            SourceFormat.XML,
            '<!DOCTYPE root [<!ENTITY x "words">]><root>&x;</root>',
            "entity declarations",
        ),
    ],
)
def test_unsupported_xml_is_explicit_and_atomic(tmp_path, fmt, text, error):
    source = tmp_path / "source.xml"
    source.write_text(text)
    with pytest.raises(Exception, match=error):
        convert_to_cusx(source, tmp_path / "book.cusx", source_format=fmt, name="Book")
    assert not (tmp_path / "book.cusx").exists()


def test_original_source_evidence_hash_is_checked(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text(PLAIN)
    package = convert_to_cusx(
        source, tmp_path / "book.cusx", source_format=SourceFormat.PLAIN, name="Book"
    )
    members, manifest, _, _ = contents(package)
    evidence = manifest["source"]["evidence"]
    members[evidence] = b"changed source"
    manifest["files"][evidence] = digest(members[evidence])
    members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(package, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    result = validate_cusx_archive(package)
    assert not result["valid"] and "source evidence" in result["reasons"][0]


def test_plain_control_character_reports_the_exact_lossless_xml_limit(tmp_path):
    source = tmp_path / "pages.txt"
    source.write_text("First page\fSecond page")
    with pytest.raises(ValueError, match=r"U\+000C.*cannot represent"):
        convert_to_cusx(source, tmp_path / "pages.cusx", source_format=SourceFormat.PLAIN, name="Pages")
    assert source.read_text() == "First page\fSecond page"
    assert not (tmp_path / "pages.cusx").exists()
