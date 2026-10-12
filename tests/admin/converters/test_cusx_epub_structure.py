import json
import zipfile
from xml.etree import ElementTree as ET

import pytest
from admin.converters.cusx import convert_to_cusx, digest, validate_cusx_archive
from admin.parsers.schema import Document, SourceFormat
from corpora_linking import CatalogEntry, SnapshotCatalog, SnapshotResolver, TextLocator

from corpora_py.linking_cusx import load_cusx_inventory

HEBREW = "וְחַטָּאִ֑ים"
XHTML = "http://www.w3.org/1999/xhtml"


def make_epub(tmp_path, *, ncx=False, missing_anchor=False, no_toc=False):
    """Small synthetic, licensed-by-test source with shared XHTML boundaries."""
    nav = '<nav epub:type="toc"><ol><li><a href="preface.xhtml">Preface</a></li>'
    nav += '<li><span>Part One</span><ol><li><a href="book.xhtml#one">One</a></li>'
    nav += '<li><a href="book.xhtml#two">Two</a></li></ol></li></ol></nav>'
    if missing_anchor:
        nav = nav.replace("#two", "#absent")
    source = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "EPUB/content.opf": (
            b'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book">'
            b'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book">demo</dc:identifier><dc:title>Book</dc:title><dc:language>he</dc:language></metadata>'
            b'<manifest><item id="preface" href="preface.xhtml" media-type="application/xhtml+xml"/>'
            b'<item id="body" href="book.xhtml" media-type="application/xhtml+xml"/>'
            b'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            b'<item id="picture" href="media/diagram.png" media-type="image/png"/>'
            b'<item id="css" href="style/book.css" media-type="text/css"/>'
            b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
            b'<spine toc="ncx"><itemref idref="preface" linear="no"/><itemref idref="body"/></spine></package>'
        ),
        "EPUB/preface.xhtml": f'<html xmlns="{XHTML}"><head/><body xml:lang="he"><p>Front matter.</p></body></html>'.encode(),
        "EPUB/book.xhtml": (
            f'<html xmlns="{XHTML}"><head><link href="style/book.css" rel="stylesheet"/></head>'
            '<body dir="rtl"><div id="outer">Before TOC. <h1 id="one">One</h1>'
            '<p id="passage">Hebrew <b>zeros</b> in on <span>וְחַ</span><span>טָּאִ֑ים</span>. 😀</p>'
            '<h1 id="two">Two</h1><p><a href="#passage">Back</a> <a href="preface.xhtml">Preface</a></p>'
            "<table><tr><td> Hebrew </td><td>words</td></tr></table>"
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            '<image xlink:href="media/diagram.png"/></svg>'
            '<img src="media/diagram.png" alt="Hebrew chart"/>'
            '<p id="note">Note <a href="#two">return</a>.</p></div></body></html>'
        ).encode(),
        "EPUB/nav.xhtml": (
            f'<html xmlns="{XHTML}" xmlns:epub="http://www.idpf.org/2007/ops"><head/><body>{nav}</body></html>'
        ).encode(),
        "EPUB/toc.ncx": (
            b'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
            b'<navPoint id="part"><navLabel><text>Part One</text></navLabel><content src="book.xhtml#one"/>'
            b'<navPoint id="one"><navLabel><text>One</text></navLabel><content src="book.xhtml#one"/></navPoint>'
            b'<navPoint id="two"><navLabel><text>Two</text></navLabel><content src="book.xhtml#two"/></navPoint>'
            b"</navPoint></navMap></ncx>"
        ),
        "EPUB/media/diagram.png": b"synthetic-image-bytes",
        "EPUB/style/book.css": b"body { direction: rtl; }",
    }
    if ncx or no_toc:
        source["EPUB/content.opf"] = source["EPUB/content.opf"].replace(b' properties="nav"', b"")
    if no_toc:
        source["EPUB/content.opf"] = (
            source["EPUB/content.opf"]
            .replace(b' toc="ncx"', b"")
            .replace(b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', b"")
        )
    path = tmp_path / "source.epub"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in source.items():
            z.writestr(name, data)
    return path, source


def convert(tmp_path, **kwargs):
    source, original = make_epub(tmp_path, **kwargs)
    path = convert_to_cusx(
        source, tmp_path / "book.cusx", source_format=SourceFormat.EPUB, name="Book"
    )
    assert validate_cusx_archive(path)["valid"]
    with zipfile.ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    return path, original, members, json.loads(members["manifest.json"])


def test_shared_file_boundaries_hierarchy_text_assets_and_links(tmp_path):
    path, source, members, manifest = convert(tmp_path)
    assert manifest["format"] == "corpora-cusx-package/0.2.0"
    # Physical file order in the ZIP/manifest differs from spine; spine wins.
    sections = [d for d in manifest["documents"] if d["source"]["path"] == "EPUB/book.xhtml"]
    assert [s["label"] for s in sections] == ["book", "One", "Two"]
    assert sections[0]["role"] == "preamble"
    assert manifest["documents"][0]["source"]["path"] == "EPUB/preface.xhtml"
    assert not manifest["documents"][0]["linear"]
    assert len(manifest["supplementary"]) == 1  # nav retained, not discarded
    toc = manifest["navigation"]["toc"]
    assert toc[1]["label"] == "Part One" and len(toc[1]["children"]) == 2
    assert [n["target"]["document_id"] for n in toc[1]["children"]] == [
        s["id"] for s in sections[1:]
    ]
    source_body = ET.fromstring(source["EPUB/book.xhtml"]).find(f"{{{XHTML}}}body")
    snapshots = [json.loads(members[s["snapshot"]]) for s in sections]
    assert "".join(s["text"] for s in snapshots) == "".join(source_body.itertext())
    assert "Hebrew zeros in on " + HEBREW + ". 😀" in snapshots[1]["text"]
    assert HEBREW in snapshots[1]["text"]  # no separator inside the Hebrew word
    assert members["assets/EPUB/media/diagram.png"] == source["EPUB/media/diagram.png"]
    assert members["assets/EPUB/style/book.css"] == source["EPUB/style/book.css"]
    tree = json.loads(members[sections[2]["tree"]])

    def walk(value):
        if isinstance(value, dict):
            yield value
            for item in value.values():
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)

    nodes = list(walk(tree))
    assert not any(n.get("children") == [] for n in nodes)
    assert any(
        n.get("type") == "svg" and n["namespace"] == "http://www.w3.org/2000/svg" for n in nodes
    )
    image = next(n for n in nodes if n.get("type") == "image")
    assert image["namespaces"]["xlink"] == "http://www.w3.org/1999/xlink"
    assert image["attrs"]["xlink:href"] == "../assets/EPUB/media/diagram.png"
    back = next(
        n for n in nodes if n.get("type") == "a" and n["source_attrs"].get("href") == "#passage"
    )
    assert back["attrs"]["href"] == sections[1]["path"].split("/")[-1] + "#passage"
    assert Document.model_validate(tree).units[0].attrs["dir"] == "rtl"
    # Continuation wrappers retain source evidence without duplicating IDs.
    assert not any(n.get("attrs", {}).get("id") == "outer" for n in nodes)


def test_each_chapter_has_exact_revision_pinned_retrieval(tmp_path):
    path, _, _, _ = convert(tmp_path)
    inventory = load_cusx_inventory(path)
    snapshot = next(s for s in inventory["snapshots"] if HEBREW in s.text)
    start = snapshot.text.index(HEBREW)
    locator = TextLocator(
        stream_id=snapshot.stream_id,
        start=start,
        end=start + len(HEBREW),
        exact=HEBREW,
        prefix=snapshot.text[max(0, start - 8) : start],
        suffix=snapshot.text[start + len(HEBREW) : start + len(HEBREW) + 8],
    )
    request = snapshot.endpoint.model_copy(update={"locators": (locator,)})
    resolver = SnapshotResolver(
        catalog=SnapshotCatalog(
            entries=(CatalogEntry(work_id=snapshot.endpoint.work_id, names=("Test book",)),)
        ),
        snapshots=inventory["snapshots"],
    )
    assert resolver.resolve(request).status == "resolved"
    assert snapshot.text[locator.start : locator.end] == HEBREW
    stale = request.model_copy(update={"revision": "sha256:" + "0" * 64})
    assert resolver.resolve(stale).status != "resolved"
    asset = next(a for a in inventory["assets"] if a["endpoint"] == snapshot.endpoint)
    assert asset["checksum"] == digest(asset["data"]) == snapshot.endpoint.revision


def test_ncx_fallback_keeps_hierarchy_and_shared_anchor_targets(tmp_path):
    _, _, _, manifest = convert(tmp_path, ncx=True)
    toc = manifest["navigation"]["toc"]
    assert toc[0]["label"] == "Part One"
    assert [n["label"] for n in toc[0]["children"]] == ["One", "Two"]
    assert toc[0]["target"] == toc[0]["children"][0]["target"]


def test_missing_toc_anchor_fails_atomically(tmp_path):
    source, _ = make_epub(tmp_path, missing_anchor=True)
    with pytest.raises(ValueError, match="Missing TOC anchor"):
        convert_to_cusx(
            source, tmp_path / "book.cusx", source_format=SourceFormat.EPUB, name="Book"
        )
    assert not (tmp_path / "book.cusx").exists()


def test_no_navigation_retains_complete_spine_with_explicit_diagnostic(tmp_path):
    _, _, _, manifest = convert(tmp_path, no_toc=True)
    assert manifest["navigation"]["toc"] == []
    assert any("No EPUB TOC" in d for d in manifest["diagnostics"])
    assert len([d for d in manifest["documents"] if d["source"]["path"] == "EPUB/book.xhtml"]) == 1


@pytest.mark.parametrize(
    "change",
    ["order", "snapshot_identity", "navigation", "wrong_document", "asset", "tree", "duplicate"],
)
def test_multi_document_contract_rejects_rehashed_corruption(tmp_path, change):
    path, _, members, manifest = convert(tmp_path)
    entry = manifest["documents"][1]
    if change == "order":
        manifest["reading_order"].reverse()
    elif change == "snapshot_identity":
        payload = json.loads(members[entry["snapshot"]])
        payload["endpoint"]["document_id"] = manifest["documents"][0]["id"]
        members[entry["snapshot"]] = json.dumps(payload).encode()
    elif change == "navigation":
        manifest["navigation"]["toc"][0]["target"]["fragment"] = "missing"
    elif change == "wrong_document":
        manifest["navigation"]["toc"][1]["children"][0]["target"] = {
            "document_id": manifest["documents"][0]["id"],
            "fragment": "",
        }
    elif change == "asset":
        del members["assets/EPUB/media/diagram.png"]
    elif change == "tree":
        payload = json.loads(members[entry["tree"]])
        payload["units"][0]["children"] = []
        members[entry["tree"]] = json.dumps(payload).encode()
    elif change == "duplicate":
        manifest["documents"][1] = manifest["documents"][0]
    manifest["files"] = {
        name: digest(data) for name, data in members.items() if name != "manifest.json"
    }
    members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    assert not validate_cusx_archive(path)["valid"]


def test_embedded_resource_urls_preserved_with_explicit_portability_diagnostic(tmp_path):
    source, members = make_epub(tmp_path)
    members["EPUB/book.xhtml"] = members["EPUB/book.xhtml"].replace(
        b'<img src="media/diagram.png"',
        b'<img srcset="media/diagram.png 1x" style="background:url(media/diagram.png)" src="media/diagram.png"',
    )
    with zipfile.ZipFile(source, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    package = convert_to_cusx(
        source, tmp_path / "book.cusx", source_format=SourceFormat.EPUB, name="Book"
    )
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert any("Embedded CSS/srcset" in d for d in manifest["diagnostics"])
        trees = [archive.read(entry["tree"]) for entry in manifest["documents"]]
        assert any(b'"srcset":"media/diagram.png 1x"' in tree for tree in trees)
    assert validate_cusx_archive(package)["valid"]
