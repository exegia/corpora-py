import json
import zipfile

import pytest
from admin.converters.cusx import convert_to_cusx, digest, validate_cusx_archive
from admin.parsers.schema import SourceFormat
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
        snapshot = TextSnapshot.model_validate_json(archive.read("snapshot.json"))
        manifest = json.loads(archive.read("manifest.json"))
        assert snapshot.text == cusx_text(archive.read("document.usx"))
        assert "😀 Selected words." in snapshot.text
        assert manifest["source"]["revision"] == digest(source.read_bytes())
        assert snapshot.endpoint.revision == digest(archive.read("document.usx"))
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
        assert "Selected words from an EPUB." in json.loads(archive.read("snapshot.json"))["text"]


def test_pdf_with_unextractable_page_rejected_atomically(tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    source = tmp_path / "scanned.pdf"
    writer.write(source)
    output = tmp_path / "scanned.cusx"
    with pytest.raises(ValueError, match="every PDF page"):
        convert_to_cusx(source, output, source_format=SourceFormat.PDF, name="Scan")
    assert not output.exists()


def test_extractable_pdf_preserves_page_metadata(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
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
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Selected PDF words.) Tj ET")
    page[NameObject("/Contents")] = stream
    source = tmp_path / "book.pdf"
    writer.write(source)
    path = convert_to_cusx(
        source, tmp_path / "book.cusx", source_format=SourceFormat.PDF, name="Book"
    )
    assert validate_cusx_archive(path)["valid"]
    with zipfile.ZipFile(path) as archive:
        document = json.loads(archive.read("document.json"))
        assert document["units"][0]["attrs"]["page_number"] == "1"
        assert "Selected PDF words." in json.loads(archive.read("snapshot.json"))["text"]


@pytest.mark.parametrize("changed", ["document.usx", "snapshot.json", "../escape"])
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


@pytest.mark.parametrize("member", ["snapshot.json", "mappings.json"])
def test_rehashed_but_invalid_payload_rejected(tmp_path, member):
    source = tmp_path / "source.txt"
    source.write_text("Selected words.")
    path = convert_to_cusx(
        source, tmp_path / "good.cusx", source_format=SourceFormat.PLAIN, name="Book"
    )
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    if member == "snapshot.json":
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
    assert ("snapshot text" if member == "snapshot.json" else "mapping evidence") in result[
        "reasons"
    ][0]
