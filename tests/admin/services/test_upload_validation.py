"""validate_upload: magic-byte sniffing, declared-format mismatch, PDF gate (issue #173)."""

from types import SimpleNamespace

import pytest
from admin.parsers.schema import SourceFormat
from admin.services import upload_validation as uv


def _write(tmp_path, data: bytes, name="upload.bin"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


class TestDetectFamily:
    @pytest.mark.parametrize(
        ("head", "family"),
        [
            (b"%PDF-1.7 rest", "pdf"),
            (b"PK\x03\x04zipdata", "zip"),
            (b"\x89PNG\r\n\x1a\n", "image"),
            (b"\xff\xd8\xff\xe0jpeg", "image"),
            (b"GIF89a", "image"),
            (b"ID3\x04tag", "audio"),
            (b"OggS...", "audio"),
            (b"\x1f\x8b\x08gzip", "archive"),
            (b"Rar!\x1a\x07", "archive"),
            (b"\x00\x01\x02binary", "binary"),
            (b"", "empty"),
            (b"just some prose", "text"),
            (b"<!DOCTYPE html><html>", "html"),
            (b"  <html lang='en'>", "html"),
            (b"<?xml version='1.0'?><TEI>", "xml"),
            (b"<TEI xmlns='x'>", "xml"),
        ],
    )
    def test_families(self, head, family):
        assert uv._detect_family(head) == family

    def test_riff_variants(self):
        assert uv._detect_family(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "audio"
        assert uv._detect_family(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image"
        assert uv._detect_family(b"RIFF\x00\x00\x00\x00AVI LIST") == "video"

    def test_mp4_ftyp_is_video(self):
        assert uv._detect_family(b"\x00\x00\x00\x18ftypmp42....") == "video"


class TestValidateUpload:
    def test_matching_text_upload_is_convertible(self, tmp_path):
        path = _write(tmp_path, b"plain prose content")
        report = uv.validate_upload(path, SourceFormat.PLAIN)
        assert report.convertible
        assert report.detected_format == "text"
        assert report.reasons == []

    def test_textual_families_cross_accept(self, tmp_path):
        # A doctype-less HTML fragment sniffs as text/xml — the parser is
        # the authority past family level, so declared html accepts it.
        path = _write(tmp_path, b"<div>fragment</div>")
        assert uv.validate_upload(path, SourceFormat.HTML).convertible
        assert uv.validate_upload(path, SourceFormat.TEI).convertible

    def test_epub_accepts_zip(self, tmp_path):
        path = _write(tmp_path, b"PK\x03\x04epubdata")
        assert uv.validate_upload(path, SourceFormat.EPUB).convertible

    def test_image_rejected_whatever_was_declared(self, tmp_path):
        path = _write(tmp_path, b"\x89PNG\r\n\x1a\nrest")
        report = uv.validate_upload(path, SourceFormat.PDF)
        assert not report.convertible
        assert "image" in report.reasons[0]

    def test_empty_file_rejected(self, tmp_path):
        report = uv.validate_upload(_write(tmp_path, b""), SourceFormat.PLAIN)
        assert not report.convertible
        assert "empty" in report.reasons[0].lower()

    def test_declared_pdf_but_zip_rejected_naming_detected(self, tmp_path):
        path = _write(tmp_path, b"PK\x03\x04not a pdf")
        report = uv.validate_upload(path, SourceFormat.PDF)
        assert not report.convertible
        assert report.declared_format == "pdf"
        assert report.detected_format == "zip"
        assert "'pdf'" in report.reasons[0] and "'zip'" in report.reasons[0]

    def test_declared_epub_but_text_rejected(self, tmp_path):
        report = uv.validate_upload(
            _write(tmp_path, b"just words"), SourceFormat.EPUB
        )
        assert not report.convertible

    def test_to_dict_shape(self, tmp_path):
        report = uv.validate_upload(_write(tmp_path, b"x"), SourceFormat.PLAIN)
        assert report.to_dict() == {
            "declared_format": "plain",
            "detected_format": "text",
            "convertible": True,
            "reasons": [],
            "warnings": [],
            "pdf": None,
        }


def _classification(pdf_type, pages_needing_ocr=(), page_count=3):
    return SimpleNamespace(
        pdf_type=pdf_type,
        confidence=0.9,
        page_count=page_count,
        pages_needing_ocr=list(pages_needing_ocr),
    )


class TestPdfClassification:
    def _validate(self, tmp_path, monkeypatch, classification):
        fake = SimpleNamespace(classify_pdf=lambda p: classification)
        monkeypatch.setitem(__import__("sys").modules, "pdf_inspector", fake)
        path = _write(tmp_path, b"%PDF-1.4 body", name="doc.pdf")
        return uv.validate_upload(path, SourceFormat.PDF)

    def test_text_based_pdf_passes_with_payload(self, tmp_path, monkeypatch):
        report = self._validate(tmp_path, monkeypatch, _classification("text_based"))
        assert report.convertible
        assert report.pdf == {
            "pdf_type": "text_based",
            "confidence": 0.9,
            "page_count": 3,
            "pages_needing_ocr": [],
        }

    @pytest.mark.parametrize("pdf_type", ["scanned", "image_based"])
    def test_textless_pdf_rejected(self, tmp_path, monkeypatch, pdf_type):
        report = self._validate(tmp_path, monkeypatch, _classification(pdf_type))
        assert not report.convertible
        assert "OCR" in report.reasons[0]
        assert report.pdf["pdf_type"] == pdf_type

    def test_mixed_pdf_warns_with_one_based_pages(self, tmp_path, monkeypatch):
        report = self._validate(
            tmp_path, monkeypatch, _classification("mixed", pages_needing_ocr=[0, 2])
        )
        assert report.convertible
        assert report.pdf["pages_needing_ocr"] == [1, 3]
        assert "1, 3" in report.warnings[0]

    def test_unreadable_pdf_rejected(self, tmp_path, monkeypatch):
        def boom(path):
            raise ValueError("Not a PDF: invalid PDF file header")

        fake = SimpleNamespace(classify_pdf=boom)
        monkeypatch.setitem(__import__("sys").modules, "pdf_inspector", fake)
        path = _write(tmp_path, b"%PDF-1.4 broken", name="doc.pdf")
        report = uv.validate_upload(path, SourceFormat.PDF)
        assert not report.convertible
        assert "could not be read" in report.reasons[0]

    def test_inspector_crash_is_not_the_uploads_fault(self, tmp_path, monkeypatch):
        def boom(path):
            raise RuntimeError("inspector internal error")

        fake = SimpleNamespace(classify_pdf=boom)
        monkeypatch.setitem(__import__("sys").modules, "pdf_inspector", fake)
        path = _write(tmp_path, b"%PDF-1.4 body", name="doc.pdf")
        report = uv.validate_upload(path, SourceFormat.PDF)
        assert report.convertible
        assert report.pdf is None
