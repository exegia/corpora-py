"""Publication fidelity and failure gates for the EPUB-to-CUSX adapter."""

import hashlib
import json
import re
import sqlite3
import zipfile

import pytest
from admin.converters import convert_epub_to_usx, validate_cusx
from lxml import etree

CX = "{urn:corpora:usx-extension:0.1}"


def make_epub(path, bodies=None, css=None):
    bodies = bodies or [
        '<h1 id="first">Chapter 1</h1>\n<p>A <b>bold</b> word and <a href="two.xhtml#end">next</a>.</p>\n'
        '<aside xmlns:epub="http://www.idpf.org/2007/ops" epub:type="footnote" id="fn"><p>Note <i>body</i>.</p></aside>'
        '<p><img src="cover.png" alt="Cover"/></p>',
        '<h1 id="end">Chapter 2</h1>\n<p>Second <span>part</span>.</p>',
    ]
    css = css or ["h1 {font-size:20pt} b {font-weight:bold}", "h1 {font-size:10pt}"]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        )
        # Manifest order deliberately differs from the spine.
        archive.writestr(
            "OPS/book.opf",
            '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>Sample Book</dc:title><dc:language>en</dc:language><dc:creator>Sample Author</dc:creator></metadata><manifest>'
            '<item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="s1" href="one.css" media-type="text/css"/>'
            '<item id="s2" href="two.css" media-type="text/css"/>'
            '<item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>'
            '</manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>',
        )
        for name, body, stylesheet in zip(["one", "two"], bodies, css, strict=True):
            archive.writestr(
                f"OPS/{name}.xhtml",
                f'<html xmlns="http://www.w3.org/1999/xhtml"><head><link rel="stylesheet" href="{name}.css"/></head><body>\n{body}\n</body></html>',
            )
            archive.writestr(f"OPS/{name}.css", stylesheet)
        archive.writestr("OPS/cover.png", b"\x89PNG\r\n\x1a\nfixture-image-bytes")
    return path


def contents(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_spine_text_notes_links_assets_styles_and_external_evidence(tmp_path):
    source = make_epub(tmp_path / "sample.epub")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    output = convert_epub_to_usx(source, tmp_path / "book.cusx")
    files = contents(output)
    assert validate_cusx(output)["stats"]["content_files"] == 2
    metadata = etree.fromstring(files["metadata.xml"])
    assert [e.get("name") for e in metadata.findall("source/structure/content")] == [
        "chapter-i",
        "chapter-ii",
    ]
    assert metadata.find("format/versedParagraphs").text == "false"
    assert metadata.find("source/canonicalContent") is None
    license_ = etree.fromstring(files["license.xml"])
    assert license_.find("publicationRights").get("status") == "unspecified"
    assert license_.find("dateLicense") is None
    assert files["release/assets/cover.png"] == b"\x89PNG\r\n\x1a\nfixture-image-bytes"
    for index, name in enumerate(["chapter-i", "chapter-ii"]):
        root = etree.fromstring(files[f"release/USX_1/{name}.usx"])
        body = etree.fromstring(contents(source)[f"OPS/{['one', 'two'][index]}.xhtml"]).find(
            "{http://www.w3.org/1999/xhtml}body"
        )
        payload = "".join("".join(e.itertext()) for e in root if e.tag in {"para", "table"})
        assert re.sub(r"\s+", "", payload) == re.sub(r"\s+", "", "".join(body.itertext()))
        assert not any("\n" in text or "\r" in text or "\t" in text for text in root.itertext())
        assert root.find("chapter").get("number") == str(index + 1)
        assert not any(e.tag == CX + "boundary" and e.get("unit") == "page" for e in root.iter())
        json_value = json.loads(files[f"release/JSON_1/{name}.json"])
        assert json_value["name"] == "document"
        assert b".xhtml" not in files[f"release/USX_1/{name}.usx"]
    first = etree.fromstring(files["release/USX_1/chapter-i.usx"])
    assert "".join(first.find(".//note").itertext()) == "Note body."
    assert first.find(".//char[@link-href]").get("link-href").startswith("chapter-ii.usx#")
    assert first.find(".//figure").get("file") == "../../release/assets/cover.png"
    styles = etree.fromstring(files["release/styles.xml"])
    h1_sizes = [
        e.find("property[@name='font-size']").text for e in styles.findall("style[@semantic='h1']")
    ]
    assert h1_sizes == ["20", "10"]  # Stylesheets stay scoped to their own documents.
    assert not any(
        "conversion" in name or name.endswith((".epub", ".sqlite", ".tf")) for name in files
    )
    with sqlite3.connect(output.with_suffix(".conversion-metadata.sqlite")) as db:
        row = db.execute(
            "SELECT source_format,source_sha256,metadata_xml FROM conversion_metadata"
        ).fetchone()
    assert row[:2] == ("epub", digest)
    assert b"source_path" in row[2] and b"tf_node" in row[2]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_table_and_inline_whitespace_are_preserved(tmp_path):
    source = make_epub(
        tmp_path / "table.epub",
        [
            '<h1>Chapter 1</h1><p>x <b>y</b> z<br/>tail</p><table>\n<tbody>\n<tr>\n<th>A</th>\n<td colspan="2">B <i>C</i></td>\n</tr>\n</tbody>\n</table>',
            "<p>End.</p>",
        ],
    )
    output = convert_epub_to_usx(source, tmp_path / "table.cusx")
    root = etree.fromstring(contents(output)["release/USX_1/chapter-i.usx"])
    assert root.find(".//cell[@colspan='2']") is not None
    assert root.find(".//optbreak") is not None
    assert validate_cusx(output)["valid"]


def test_clean_content_preserves_inline_word_separators_and_empty_markers(tmp_path):
    source = make_epub(
        tmp_path / "whitespace.epub",
        [
            '<h1>Chapter 1</h1>\n  <p> \n A\t <b>bold</b>\n word.  </p>\n'
            '<p><i>first</i> \n <b>second</b></p>'
            '<p>A<span> \n </span>B<a id="empty"/> C.</p>'
            '<p>漢<b>字</b>。</p><p> \n\t </p>',
            "<p>End.</p>",
        ],
    )
    files = contents(convert_epub_to_usx(source, tmp_path / "whitespace.cusx"))
    root = etree.fromstring(files["release/USX_1/chapter-i.usx"])
    paragraphs = ["".join(p.itertext()) for p in root.findall("para")]
    assert paragraphs == ["Chapter 1", "A bold word.", "first second", "A B C.", "漢字。"]
    value = json.loads(files["release/JSON_1/chapter-i.json"])

    def inspect(node):
        content = node.get("content")
        if content is None:
            return
        assert content
        assert any(isinstance(item, dict) or item.strip() for item in content)
        for item in content:
            if isinstance(item, dict):
                inspect(item)
            else:
                assert item and not any(char in item for char in "\r\n\t")
                assert "  " not in item

    inspect(value)
    markers = [item for item in value["content"] if item["name"] == "chapter"]
    assert len(markers) == 2 and all("content" not in item for item in markers)
    anchor = root.find(".//char[@link-id]")
    assert anchor is not None


def test_grouped_notes_and_tei_labels_are_auxiliary_content(tmp_path):
    source = make_epub(
        tmp_path / "notes.epub",
        [
            '<p>Main.</p><div class="note"><p>Grouped <i>note</i>.</p></div>',
            '<h2>Notes</h2><dl class="tei tei-list-footnotes">\n'
            '<dt class="tei tei-notelabel"><a id="note_1" href="one.xhtml">1</a></dt>\n'
            '<dd class="tei tei-notetext"><p>Footnote <b>body</b>.</p></dd>\n</dl>',
        ],
    )
    output = convert_epub_to_usx(source, tmp_path / "notes.cusx")
    files = contents(output)
    metadata = etree.fromstring(files["metadata.xml"])
    roots = [
        etree.fromstring(files[e.get("src")])
        for e in metadata.find("source/structure").iter("content")
    ]
    notes = [note for root in roots for note in root.iter("note")]
    assert len(notes) == 2
    assert ["".join(n.itertext()) for n in notes] == ["Grouped note.", "1 Footnote body."]
    # The label's canonical anchor and backlink remain inside its note.
    assert notes[1].find(".//char[@link-id]") is not None
    main = "".join(
        str(value)
        for root in roots
        for value in root.xpath(
            ".//text()[not(ancestor::note) and not(ancestor::cx:title)]",
            namespaces={"cx": CX[1:-1]},
        )
    )
    assert "Grouped note." not in main and "Footnote body." not in main
    assert validate_cusx(output)["valid"]


@pytest.mark.parametrize(
    "body",
    [
        '<p><a href="missing.xhtml#nope">Bad</a></p>',
        "<script>alert(1)</script>",
        '<p id="same">A</p><p id="same">B</p>',
        "<math><mi>x</mi></math>",
        '<table><tr><td rowspan="2">A</td></tr></table>',
    ],
)
def test_unsupported_or_broken_content_does_not_replace_an_existing_archive(tmp_path, body):
    source = make_epub(tmp_path / "bad.epub", [body, "<p>End</p>"])
    output = tmp_path / "existing.cusx"
    output.write_bytes(b"existing archive")
    with pytest.raises(ValueError):
        convert_epub_to_usx(source, output)
    assert output.read_bytes() == b"existing archive"
    assert not output.with_suffix(".conversion-metadata.sqlite").exists()
    assert not list(tmp_path.glob(".cusx-*"))


def test_manifest_tampering_json_mismatch_and_path_escape_are_rejected(tmp_path):
    source = make_epub(tmp_path / "sample.epub")
    files = contents(convert_epub_to_usx(source, tmp_path / "book.cusx"))
    original_files = dict(files)
    files["release/assets/cover.png"] = b"altered"
    damaged = tmp_path / "damaged.cusx"
    with zipfile.ZipFile(damaged, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="PKG-004"):
        validate_cusx(damaged)
    files = original_files
    key = "release/JSON_1/chapter-i.json"
    value = json.loads(files[key])
    value["attributes"]["id"] = "different"
    files[key] = json.dumps(value).encode()
    metadata = etree.fromstring(files["metadata.xml"])
    resource = metadata.find(f"manifest/resource[@uri='{key}']")
    resource.set("size", str(len(files[key])))
    resource.set("checksum", hashlib.sha256(files[key]).hexdigest())
    files["metadata.xml"] = etree.tostring(metadata)
    with zipfile.ZipFile(damaged, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="PKG-009"):
        validate_cusx(damaged)
    with zipfile.ZipFile(damaged, "w") as archive:
        archive.writestr("../escape.xml", b"unsafe")
    with pytest.raises(ValueError, match="escapes"):
        validate_cusx(damaged)


def test_output_extension_and_evidence_source_collision_are_rejected(tmp_path):
    source = make_epub(tmp_path / "sample.epub")
    with pytest.raises(ValueError, match="extension"):
        convert_epub_to_usx(source, tmp_path / "book.zip")
    with pytest.raises(ValueError, match="distinct"):
        convert_epub_to_usx(source, tmp_path / "book.cusx", evidence_path=source)
