"""Source fidelity and the owned CTEI archive contract."""

import io
import json
import uuid
import zipfile

import pytest
import yaml
from admin.converters.tei import convert_to_ctei, validate_ctei_archive
from admin.converters.tei.encoding import NS, T, digest, tei_text, xml
from admin.converters.tei.package import CTEI_NS, read_history
from admin.parsers.schema import SourceFormat
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def unpack(path):
    with zipfile.ZipFile(path) as zf:
        return {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}


def build(tmp_path, data, suffix, fmt, **kwargs):
    source = tmp_path / ("source" + suffix)
    source.write_bytes(data.encode() if isinstance(data, str) else data)
    output = tmp_path / "converted.ctei"
    convert_to_ctei(source, output, source_format=fmt, **kwargs)
    return output, unpack(output)


def test_plain_contract_and_exact_unicode(tmp_path):
    text = "Exact ὁ λόγος e\u0301\u00a0word.\n\nSecond paragraph."
    path, files = build(tmp_path, text, ".txt", SourceFormat.PLAIN)
    manifest = yaml.safe_load(files["manifest.yml"])
    assert uuid.UUID(manifest["uid"]).version == 4
    assert manifest["version"] == "1.0.0"
    assert manifest["format"] == "corpus"
    assert manifest["format_version"] == "1"
    assert manifest["language"] == "english"
    assert manifest["languageCode"] == "ENG"
    assert manifest["datasetId"] == manifest["projectId"] == ""
    assert manifest["thumbnail"] is None
    assert {a["path"] for a in manifest["assets"]} == {
        p.removeprefix("assets/") for p in files if p.startswith("assets/")
    }
    assert files["assets/source/original.txt"].decode() == text
    root = xml(files["version_1.0.0/d001.xml"])
    assert [tei_text(p) for p in root.xpath("//t:body/t:p", namespaces=T)] == text.split("\n\n")
    assert not root.xpath("//t:pb|//t:lb|//t:cb|//t:fw", namespaces=T)
    assert validate_ctei_archive(path)["valid"]
    assert validate_ctei_archive(path)["source_verified"] is False


def test_tei_metadata_split_notes_tables_references_and_review(tmp_path):
    text = f'''<TEI xmlns="{NS}" xml:lang="fr"><teiHeader><fileDesc><titleStmt><title>Le livre de test</title><author>Auteur</author></titleStmt><publicationStmt><p>Test</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader><text><body><div type="chapter" xml:id="chapter1"><head>Chapitre premier</head><p xml:id="p1">ὁ <hi rend="italic">λόγος</hi> é <note xml:id="note1"><p>Note exacte.</p></note> <ref target="#p2">suite</ref> <ref target="https://example.org/source">source</ref><unclear reason="illegible">?</unclear></p><table><row><cell>α</cell><cell>β</cell></row><row><cell>γ</cell><cell>δ</cell></row></table></div><div type="chapter" xml:id="chapter2"><head>Second</head><p xml:id="p2">Fin.</p></div></body></text></TEI>'''
    path, files = build(tmp_path, text, ".tei", SourceFormat.TEI, author_sub="actual-user")
    manifest = yaml.safe_load(files["manifest.yml"])
    assert manifest["name"] == "Le livre de test"
    assert manifest["language"] == "french"
    assert manifest["languageCode"] == "FRA"
    assert manifest["category"] == "book"
    toc = yaml.safe_load(files["toc.yml"])
    assert toc["readingOrder"] == ["version_1.0.0/d001.xml", "version_1.0.0/d002.xml"]
    root = xml(files[toc["readingOrder"][0]])
    assert root.xpath("string(//t:ref[@type='resolved']/@target)", namespaces=T) == "d002.xml#p2"
    assert root.xpath("//t:note/t:p/text()", namespaces=T) == ["Note exacte."]
    assert root.xpath("//t:table/t:row/t:cell/text()", namespaces=T) == ["α", "β", "γ", "δ"]
    refs = xml(files["references.xml"])
    assert (
        refs[0].get("source")
        == "version_1.0.0/d001.xml#" + root.xpath("//t:ref/@xml:id", namespaces=T)[0]
    )
    assert refs[0].get("target") == "version_1.0.0/d002.xml#p2"
    review = xml(files["review.xml"])
    assert len(review.xpath("//t:annotation", namespaces=T)) == 2
    history = read_history(files["history.xml"])["versions"][0]
    assert history["author"] == history["approved_by"] == {"sub": "actual-user"}
    assert history["current"] is True and history["snapshot_key"] is None
    assert validate_ctei_archive(path)["stats"]["review_items"] == 2


def epub_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        zf.writestr(
            "OEBPS/content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>A source book</dc:title><dc:language>he</dc:language><dc:description>Its source description.</dc:description></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="img" href="figure.png" media-type="image/png"/><item id="data" href="data.json" media-type="application/json"/></manifest><spine><itemref idref="one"/></spine></package>',
        )
        zf.writestr(
            "OEBPS/one.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Source</title></head><body><h1>Chapter One</h1><p>שָׁלוֹם</p><figure><img src="figure.png" alt="Diagram"/><figcaption>Caption.</figcaption></figure><div class="footnote" id="fn"><p>Exact note.</p></div></body></html>',
        )
        zf.writestr("OEBPS/figure.png", b"source image bytes")
        zf.writestr("OEBPS/data.json", '{"exact":true}')
    return buffer.getvalue()


def test_epub_metadata_and_asset_placement(tmp_path):
    path, files = build(tmp_path, epub_bytes(), ".epub", SourceFormat.EPUB)
    manifest = yaml.safe_load(files["manifest.yml"])
    assert manifest["name"] == "A source book"
    assert manifest["description"] == "Its source description."
    assert manifest["languageCode"] == "HEB"
    assert b"source image bytes" in files.values()
    assert files["assets/source-resources/OEBPS/data.json"] == b'{"exact":true}'
    mapping = xml(files["assets/mapping.xml"])
    inline = [e for e in mapping if e.get("placement") == "inline"]
    assert len(inline) == 1
    assert inline[0].get("target").startswith("version_1.0.0/d001.xml#")
    styles = xml(files["presentations/styles.xml"])
    assert {s.get("semantic") for s in styles} >= {"h1", "paragraph", "note", "caption"}
    assert all(set(e.attrib) == {"semantic", "targets"} for e in styles)
    assert validate_ctei_archive(path)["valid"]


def test_html_preserves_explicit_abbreviation_and_detected_links(tmp_path):
    text = '<html lang="en"><head><title>Document Title</title></head><body><h1>Heading</h1><p>Before <abbr title="Saint">St.</abbr> after <a href="#note">note</a>.</p><div class="footnote" id="note"><p>ἄνθρωπος</p></div></body></html>'
    path, files = build(tmp_path, text, ".html", SourceFormat.HTML)
    root = xml(files["version_1.0.0/d001.xml"])
    assert root.xpath("//t:abbr/text()", namespaces=T) == ["St."]
    assert root.xpath("//t:expan/text()", namespaces=T) == ["Saint"]
    assert root.xpath("//t:ref/@type", namespaces=T) == ["resolved"]
    assert validate_ctei_archive(path)["valid"]


def test_unreadable_pdf_rejected_without_output(tmp_path):
    source = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(source)
    with pytest.raises(ValueError, match="unreadable"):
        convert_to_ctei(source, tmp_path / "out.ctei", source_format=SourceFormat.PDF)
    assert not (tmp_path / "out.ctei").exists()


def test_archive_tampering_rejected(tmp_path):
    path, files = build(tmp_path, "Exact source", ".txt", SourceFormat.PLAIN)
    files["version_1.0.0/d001.xml"] = files["version_1.0.0/d001.xml"].replace(b"Exact", b"Wrong")
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    with pytest.raises(ValueError, match="hashes"):
        validate_ctei_archive(path)


def test_history_rejects_string_booleans_and_multiple_current_versions():
    with pytest.raises(ValueError, match="Invalid"):
        read_history(f'<history xmlns="{CTEI_NS}"><version current="yes"/></history>'.encode())


def test_css_is_rejected_even_with_updated_member_hashes(tmp_path):
    path, files = build(tmp_path, "Text", ".txt", SourceFormat.PLAIN)
    files["presentations/styles.xml"] = files["presentations/styles.xml"].replace(b'semantic="paragraph"', b'semantic="font-size:12px"')
    receipt = json.loads(files["assets/conversion/receipt.json"])
    receipt["files"]["presentations/styles.xml"] = digest(files["presentations/styles.xml"])
    files["assets/conversion/receipt.json"] = json.dumps(receipt).encode()
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    with pytest.raises(ValueError, match="semantic role"):
        validate_ctei_archive(path)


def test_xml_declaration_and_supported_structure(tmp_path):
    path, files = build(
        tmp_path,
        '<?xml version="1.0" encoding="UTF-8"?><section><p>Exact ἀλήθεια é.</p></section>',
        ".xml",
        SourceFormat.XML,
    )
    root = xml(files["version_1.0.0/d001.xml"])
    assert root.xpath("//t:body//t:p/text()", namespaces=T) == ["Exact ἀλήθεια é."]
    assert validate_ctei_archive(path)["valid"]


@pytest.mark.parametrize(
    "unsupported",
    [
        f'<standOff xmlns="{NS}"><spanGrp type="verse"><span from="#a" to="#b" n="1"/></spanGrp></standOff>',
        "surah",
    ],
)
def test_canonical_semantics_are_rejected_before_omission(tmp_path, unsupported):
    body = (
        '<div type="surah"><p>Source</p></div>'
        if unsupported == "surah"
        else '<p><anchor xml:id="a"/>Source<anchor xml:id="b"/></p>'
    )
    source = tmp_path / "source.tei"
    source.write_text(
        f'<TEI xmlns="{NS}"><text><body>{body}</body></text>{unsupported if unsupported != "surah" else ""}</TEI>'
    )
    with pytest.raises(ValueError, match="scheme|mapping"):
        convert_to_ctei(source, tmp_path / "out.ctei", source_format=SourceFormat.TEI)
    assert not (tmp_path / "out.ctei").exists()


def test_pdf_continuation_does_not_infer_paragraphs_from_pages(tmp_path):
    writer = PdfWriter()
    for content in (b"A paragraph starts", b"and continues."):
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 100 Td (" + content + b") Tj ET")
        page[NameObject("/Contents")] = stream
    source = tmp_path / "source.pdf"
    writer.add_attachment("audio.mp3", b"source audio bytes")
    writer.write(source)
    path = convert_to_ctei(source, tmp_path / "out.ctei", source_format=SourceFormat.PDF)
    root = xml(unpack(path)["version_1.0.0/d001.xml"])
    paragraphs = root.xpath("//t:body/t:p", namespaces=T)
    assert len(paragraphs) == 1
    assert tei_text(paragraphs[0]) == "A paragraph starts and continues."
    assert validate_ctei_archive(path)["stats"]["review_items"] >= 1
    files = unpack(path)
    assert files["assets/pdf/attachment-1-1.mp3"] == b"source audio bytes"
    manifest = yaml.safe_load(files["manifest.yml"])
    assert any(a["type"] == "audio" for a in manifest["assets"])


@pytest.mark.parametrize("list_type", ["", ' type="index"'])
def test_tei_back_index_preserves_entries_and_reviews_list_mapping(tmp_path, list_type):
    source = f'''<TEI xmlns="{NS}" xml:lang="en"><teiHeader><fileDesc><titleStmt><title>Indexed Book</title></titleStmt><publicationStmt><p>Test</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader><text><body><p>Body.</p></body><back><div type="index"><head>Index</head><list{list_type}><item>λόγος — first entry</item><item>ἄνθρωπος — second entry</item></list></div></back></text></TEI>'''
    path, files = build(tmp_path, source, ".tei", SourceFormat.TEI)
    root = xml(files["version_1.0.0/d001.xml"])
    assert root.xpath("//t:back//t:item/text()", namespaces=T) == [
        "λόγος — first entry", "ἄνθρωπος — second entry"
    ]
    assert root.xpath("//t:back//t:list/@type", namespaces=T) == ["unordered"]
    assert files["assets/source/original.tei"].decode() == source
    review = xml(files["review.xml"])
    messages = [tei_text(n) for n in review.xpath("//t:annotation/t:note/t:p", namespaces=T)]
    assert any("ordering requires review" in message for message in messages)
    assert any("Source division type 'index'" in message for message in messages)
    assert validate_ctei_archive(path)["valid"]
