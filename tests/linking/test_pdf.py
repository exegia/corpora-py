"""Actual tiny PDF fixtures, including rejection of unsupported transforms."""

import io

import pytest
from corpora_linking import BibleBook, BibleCitationDetector, Endpoint
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from corpora_py.linking_conversion import detect_converted_references
from corpora_py.linking_pdf import extract_pdf_references_input, sha256_revision

pytest.importorskip("pdfplumber")


def pdf_bytes(*, rotation=0, crop=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 150 Td (Compare John 3:16.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    if rotation:
        page.rotate(rotation)
    if crop:
        page.cropbox.lower_left = (10, 10)
    writer.add_blank_page(width=300, height=200)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def endpoints(data):
    original = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="pdf",
        revision=sha256_revision(data),
        document_id="file",
    )
    converted = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="text",
        revision=sha256_revision(b"Compare John 3:16.\f"),
        document_id="file",
    )
    return original, converted


def test_real_pdf_extraction_geometry_mapping_and_detection():
    data = pdf_bytes()
    original, converted = endpoints(data)
    conversion = extract_pdf_references_input(
        data, original=original, converted=converted, asset_id="pdf"
    )
    assert conversion.converted.text == "Compare John 3:16.\f"
    assert len(conversion.mappings) == 3
    for mapping in conversion.mappings:
        native = mapping.original.locators[0]
        assert native.page == 1 and native.rectangles[0].x0 >= 20
        assert 30 < native.rectangles[0].y0 < 50
        assert mapping.original.revision == sha256_revision(data)
        assert mapping.fidelity == "approximate"
    detector = BibleCitationDetector(
        books=(BibleBook(work_id="john", aliases=("John",)),),
        stream_id="body",
        profile="fixture",
        scheme_id="fixture",
        scheme_version="1",
        agent_id="test",
    )
    (record,) = detect_converted_references(conversion, detector).references
    assert record.reference.source.locators[0].exact == "John 3:16"
    assert len(record.mappings) == 2
    assert "approximate original location evidence" in record.diagnostics


@pytest.mark.parametrize("changes", [{"rotation": 90}, {"crop": True}])
def test_unsupported_page_transforms_reject(changes):
    data = pdf_bytes(**changes)
    original, converted = endpoints(data)
    with pytest.raises(ValueError, match="unsupported PDF"):
        extract_pdf_references_input(data, original=original, converted=converted, asset_id="pdf")


def test_changed_asset_and_converted_revision_reject():
    data = pdf_bytes()
    original, converted = endpoints(data)
    wrong = Endpoint.model_validate({**original.model_dump(), "revision": "sha256:wrong"})
    with pytest.raises(ValueError, match="original PDF checksum"):
        extract_pdf_references_input(data, original=wrong, converted=converted, asset_id="pdf")
    wrong = Endpoint.model_validate({**converted.model_dump(), "revision": "sha256:wrong"})
    with pytest.raises(ValueError, match="converted text checksum"):
        extract_pdf_references_input(data, original=original, converted=wrong, asset_id="pdf")
