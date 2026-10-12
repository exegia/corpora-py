import json
import zipfile
from pathlib import Path

import pytest
from admin.converters.cusx import (
    LEGACY_PROFILE,
    convert_to_cusx,
    digest,
    document_xml,
    encoded,
    validate_cusx_archive,
)
from admin.parsers.schema import Document, DocumentMetadata, SourceFormat, Unit, tokenize
from corpora_linking import TextSnapshot

from corpora_py.linking_cusx import cusx_text


@pytest.mark.parametrize(
    "fmt,content",
    [
        (SourceFormat.PLAIN, "Before. 😀 Selected words. After.\n\nSecond paragraph."),
        (
            SourceFormat.HTML,
            "<html><head><title>Book</title></head><body><p>😀 Selected words.</p></body></html>",
        ),
        (SourceFormat.XML, "<book><chapter><p>😀 Selected words.</p></chapter></book>"),
        (SourceFormat.TEI, "<TEI><text><body><p>😀 Selected words.</p></body></text></TEI>"),
    ],
)
def test_convert_real_sources_and_verify_linking_stream(tmp_path, fmt, content):
    source = tmp_path / "source"
    source.write_text(content, encoding="utf-8")
    path = convert_to_cusx(source, tmp_path / "book.cusx", source_format=fmt, name="Book")
    assert validate_cusx_archive(path)["valid"]
    with zipfile.ZipFile(path) as archive:
        snapshot = TextSnapshot.model_validate_json(archive.read("snapshots/0001.json"))
        manifest = json.loads(archive.read("manifest.json"))
        assert snapshot.text == cusx_text(archive.read("documents/0001.usx"))
        assert "😀 Selected words." in snapshot.text
        assert manifest["source"]["revision"] == digest(source.read_bytes())
        assert snapshot.endpoint.revision == digest(archive.read("documents/0001.usx"))
        assert json.loads(archive.read("references.json")) == []
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())
        assert not any(name.endswith(".tf") for name in archive.namelist())


def test_epub_conversion(tmp_path):
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("demo")
    book.set_title("Demo book")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Chapter", file_name="chapter.xhtml", lang="en")
    chapter.content = "<p>Selected words from an EPUB.</p>"
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [chapter]
    source = tmp_path / "book.epub"
    epub.write_epub(str(source), book)
    output = convert_to_cusx(
        source, tmp_path / "book.cusx", source_format=SourceFormat.EPUB, name="Book"
    )
    assert validate_cusx_archive(output)["valid"]
    with zipfile.ZipFile(output) as archive:
        assert (
            "Selected words from an EPUB."
            in json.loads(archive.read("snapshots/0001.json"))["text"]
        )


def test_pdf_ocr_failure_rejected_atomically(tmp_path, monkeypatch):
    from admin.parsers import pdf_ocr
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    source = tmp_path / "scanned.pdf"
    writer.write(source)
    output = tmp_path / "scanned.cusx"

    def fail(source):
        raise ValueError("OCR failed; no partial conversion accepted")

    monkeypatch.setattr(pdf_ocr, "extract_pdf", fail)
    with pytest.raises(ValueError, match="no partial conversion accepted"):
        convert_to_cusx(source, output, source_format=SourceFormat.PDF, name="Scan")
    assert not output.exists()


def test_forced_ocr_pdf_preserves_page_metadata(tmp_path, pinned_pdf_ocr):
    source = Path(__file__).parents[1] / "fixtures/cusx/outlined.pdf"
    path = convert_to_cusx(
        source, tmp_path / "book.cusx", source_format=SourceFormat.PDF, name="Book"
    )
    assert validate_cusx_archive(path)["valid"]
    with zipfile.ZipFile(path) as archive:
        document = json.loads(archive.read("trees/0001.json"))
        assert document["units"][0]["attrs"]["page_number"] == "1"
        assert "Unicode café" in json.loads(archive.read("snapshots/0001.json"))["text"]
        assert "assets/pdf/ocr/provenance.json" in archive.namelist()


@pytest.mark.parametrize("changed", ["documents/0001.usx", "snapshots/0001.json", "../escape"])
def test_corrupted_or_unsafe_package_rejected(tmp_path, changed):
    source = tmp_path / "source.txt"
    source.write_text("Selected words.")
    output = convert_to_cusx(
        source, tmp_path / "good.cusx", source_format=SourceFormat.PLAIN, name="Book"
    )
    with zipfile.ZipFile(output) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents[changed] = b"broken"
    with zipfile.ZipFile(tmp_path / "bad.cusx", "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    assert not validate_cusx_archive(tmp_path / "bad.cusx")["valid"]


@pytest.mark.parametrize("member", ["snapshots/0001.json", "mappings.json"])
def test_rehashed_but_invalid_payload_rejected(tmp_path, member):
    source = tmp_path / "source.txt"
    source.write_text("Selected words.")
    path = convert_to_cusx(
        source, tmp_path / "good.cusx", source_format=SourceFormat.PLAIN, name="Book"
    )
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    if member == "snapshots/0001.json":
        snapshot = json.loads(contents[member])
        snapshot["text"] = "Different words."
        contents[member] = json.dumps(snapshot).encode()
    else:
        contents[member] = b"[]"
    manifest = json.loads(contents["manifest.json"])
    manifest["files"][member] = digest(contents[member])
    contents["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    result = validate_cusx_archive(path)
    assert not result["valid"]
    assert ("snapshot text" if member == "snapshots/0001.json" else "mapping evidence") in result[
        "reasons"
    ][0]


def test_whitespace_and_carriage_return_scalars_are_not_normalized(tmp_path):
    content = "  Before.\r\n\r\n Hebrew וְחַטָּאִ֑ים\u00a0after.\t"
    source = tmp_path / "notes.txt"
    source.write_bytes(content.encode())
    path = convert_to_cusx(
        source, tmp_path / "book.cusx", source_format=SourceFormat.PLAIN, name="Book"
    )
    with zipfile.ZipFile(path) as archive:
        snapshot = TextSnapshot.model_validate_json(archive.read("snapshots/0001.json"))
        assert snapshot.text == content


def test_existing_v01_packages_keep_their_original_projection(tmp_path):
    from xml.etree import ElementTree as ET

    document = Document(
        metadata=DocumentMetadata(source_format=SourceFormat.PLAIN),
        units=[Unit(type="paragraph", tokens=tokenize("Old package."))],
    )
    data = document_xml(document, profile=LEGACY_PROFILE)
    identity = {
        "work_id": "w",
        "edition_id": "e",
        "package_id": "p",
        "document_id": "document.usx",
        "revision": digest(data),
        "locators": [],
    }
    members = {
        "document.usx": data,
        "document.json": encoded(document.model_dump(mode="json")),
        "snapshot.json": encoded(
            {
                "endpoint": identity,
                "stream_id": "cusx-itertext/v1",
                "text": "".join(ET.fromstring(data).itertext()),
            }
        ),
        "references.json": b"[]",
        "mappings.json": b'{"mappings":[]}',
    }
    manifest = {
        "format": LEGACY_PROFILE,
        "files": {p: digest(v) for p, v in members.items()},
        "identity": identity,
        "stream": {
            "id": "cusx-itertext/v1",
            "offset_unit": "unicode-scalar",
            "normalization": "preserve",
        },
    }
    output = tmp_path / "old.cusx"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", encoded(manifest))
        for p, v in members.items():
            archive.writestr(p, v)
    assert validate_cusx_archive(output)["valid"]
