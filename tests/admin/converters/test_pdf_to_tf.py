"""convert_pdf_to_tf: markdown route, OCR warnings, per-page fallback (issue #175)."""

import sys
from types import SimpleNamespace

import pytest
from admin.converters._pdf_to_tf import convert_pdf_to_tf
from admin.parsers.schema import CorpusCategory


def build_pdf(texts: list[str], *, title: str | None = None) -> bytes:
    """A minimal valid PDF, one page per text, with computed xref offsets.

    pypdf refuses PDFs whose xref offsets are wrong, so the table is
    assembled from the real byte positions rather than hard-coded.
    """
    n = len(texts)
    font_id = 3 + 2 * n
    info_id = font_id + 1 if title else None
    objects: dict[int, bytes] = {}
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()
    for i, text in enumerate(texts):
        page_id, content_id = 3 + 2 * i, 4 + 2 * i
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ).encode()
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    if info_id:
        objects[info_id] = f"<< /Title ({title}) >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(out)
        out += f"{obj_id} 0 obj\n".encode() + objects[obj_id] + b"\nendobj\n"
    xref_at = len(out)
    count = max(objects) + 1
    out += f"xref\n0 {count}\n".encode() + b"0000000000 65535 f \n"
    for obj_id in range(1, count):
        out += f"{offsets[obj_id]:010d} 00000 n \n".encode()
    trailer = f"<< /Size {count} /Root 1 0 R"
    if info_id:
        trailer += f" /Info {info_id} 0 R"
    trailer += " >>"
    out += f"trailer\n{trailer}\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def _inspection(markdown, pdf_type="text_based", pages_needing_ocr=(), title=None):
    return SimpleNamespace(
        pdf_type=pdf_type,
        markdown=markdown,
        title=title,
        pages_needing_ocr=list(pages_needing_ocr),
    )


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(build_pdf(["Page one text here"], title="Inspected Title"))
    return path


def _fake_inspector(monkeypatch, result_or_exc):
    def process_pdf_bytes(data):
        if isinstance(result_or_exc, Exception):
            raise result_or_exc
        return result_or_exc

    fake = SimpleNamespace(process_pdf_bytes=process_pdf_bytes)
    monkeypatch.setitem(sys.modules, "pdf_inspector", fake)


_BOOKISH_MARKDOWN = (
    "# Chapter One\n\nOpening words of the story\n\n"
    "# Chapter Two\n\nAnd then some more prose\n"
)


class TestMarkdownRoute:
    def test_headings_become_chapter_sections(self, pdf_path, tmp_path, monkeypatch):
        _fake_inspector(monkeypatch, _inspection(_BOOKISH_MARKDOWN))
        result = convert_pdf_to_tf(str(pdf_path), tmp_path / "tf")
        assert result.category is CorpusCategory.BOOK
        assert result.warnings == []
        otext = (tmp_path / "tf" / "otext.tf").read_text()
        assert "@sectionTypes=book,chapter" in otext
        label = (tmp_path / "tf" / "label.tf").read_text()
        assert "Chapter One" in label and "Chapter Two" in label

    def test_flat_markdown_is_a_document(self, pdf_path, tmp_path, monkeypatch):
        _fake_inspector(monkeypatch, _inspection("Just prose\n\nwith paragraphs\n"))
        result = convert_pdf_to_tf(str(pdf_path), tmp_path / "tf")
        assert result.category is CorpusCategory.DOCUMENT
        otext = (tmp_path / "tf" / "otext.tf").read_text()
        assert "@sectionTypes=book\n" in otext

    def test_mixed_pdf_warns_with_one_based_pages(self, pdf_path, tmp_path, monkeypatch):
        _fake_inspector(
            monkeypatch,
            _inspection(_BOOKISH_MARKDOWN, pdf_type="mixed", pages_needing_ocr=[0, 2]),
        )
        result = convert_pdf_to_tf(str(pdf_path), tmp_path / "tf")
        assert any("2 page(s) need OCR" in w and "1, 3" in w for w in result.warnings)

    def test_inspector_title_fills_missing_metadata(self, tmp_path, monkeypatch):
        path = tmp_path / "untitled.pdf"
        path.write_bytes(build_pdf(["body text"]))  # no /Info title
        _fake_inspector(
            monkeypatch, _inspection(_BOOKISH_MARKDOWN, title="Recovered Title")
        )
        convert_pdf_to_tf(str(path), tmp_path / "tf")
        title = (tmp_path / "tf" / "title.tf").read_text()
        assert "Recovered Title" in title

    def test_pdf_metadata_title_wins_over_inspector(self, pdf_path, tmp_path, monkeypatch):
        _fake_inspector(
            monkeypatch, _inspection(_BOOKISH_MARKDOWN, title="Inspector Guess")
        )
        convert_pdf_to_tf(str(pdf_path), tmp_path / "tf")
        title = (tmp_path / "tf" / "title.tf").read_text()
        assert "Inspected Title" in title
        assert "Inspector Guess" not in title


class TestRejection:
    @pytest.mark.parametrize("pdf_type", ["scanned", "image_based"])
    def test_textless_pdf_raises_not_falls_back(
        self, pdf_path, tmp_path, monkeypatch, pdf_type
    ):
        _fake_inspector(monkeypatch, _inspection("", pdf_type=pdf_type))
        with pytest.raises(ValueError, match="OCR is required"):
            convert_pdf_to_tf(str(pdf_path), tmp_path / "tf")

    def test_empty_markdown_raises(self, pdf_path, tmp_path, monkeypatch):
        _fake_inspector(monkeypatch, _inspection(""))
        with pytest.raises(ValueError, match="no extractable text"):
            convert_pdf_to_tf(str(pdf_path), tmp_path / "tf")


class TestPerPageFallback:
    def test_inspector_crash_falls_back_to_pages(self, tmp_path, monkeypatch):
        path = tmp_path / "doc.pdf"
        path.write_bytes(build_pdf(["First page words", "Second page words"]))
        _fake_inspector(monkeypatch, RuntimeError("inspector exploded"))
        result = convert_pdf_to_tf(str(path), tmp_path / "tf")
        assert result.category is CorpusCategory.DOCUMENT
        otype = (tmp_path / "tf" / "otype.tf").read_text()
        assert "page" in otype
        text = (tmp_path / "tf" / "text.tf").read_text()
        assert "First" in text and "Second" in text


class TestRealInspector:
    def test_text_based_pdf_end_to_end(self, tmp_path):
        # No fake: the real pdf_inspector classifies and extracts a
        # hand-built two-page PDF (guards the integration itself).
        pytest.importorskip("pdf_inspector")
        path = tmp_path / "real.pdf"
        path.write_bytes(
            build_pdf(
                ["Hello World test document", "Second page of running text here"],
                title="Real Deal",
            )
        )
        convert_pdf_to_tf(str(path), tmp_path / "tf")
        # The inspector renders each page's single line as a `##` heading,
        # so the words land on section labels rather than slot text.
        extracted = (tmp_path / "tf" / "label.tf").read_text() + (
            tmp_path / "tf" / "text.tf"
        ).read_text()
        assert "Hello" in extracted
        assert "Second" in extracted
