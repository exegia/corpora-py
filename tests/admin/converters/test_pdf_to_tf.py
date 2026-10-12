"""Forced PDF OCR -> TF: actual recorded SDK output, no native fallback."""

from pathlib import Path

import pytest
from admin.converters import _pdf_to_tf
from admin.parsers.pdf_ocr import digest
from admin.parsers.schema import SourceFormat
from admin.services.conversion import run_conversion
from tf.fabric import Fabric

PDF = Path(__file__).parents[1] / "fixtures/cusx/outlined.pdf"


def test_ocr_pages_geometry_and_snapshot_survive_tf(tmp_path, pinned_pdf_ocr):
    result = _pdf_to_tf.convert_pdf_to_tf(str(PDF), tmp_path / "tf")
    api = Fabric(locations=str(result), silent="deep").loadAll(silent="deep")
    assert api
    pages = api.F.otype.s("page")
    assert [api.F.page_number.v(p) for p in pages] == ["1", "2"]
    assert api.F.provenance.data
    assert (Path(result) / "pdf-ocr/source.pdf").read_bytes() == PDF.read_bytes()
    snapshot = Path(result) / "pdf-ocr/snapshot.json"
    assert digest(snapshot.read_bytes()) == pinned_pdf_ocr["provenance"]["snapshot_sha256"]


def test_ocr_failure_never_falls_back_to_native_text(tmp_path, monkeypatch):
    def fail(source):
        raise ValueError("Pinned forced PDF OCR failed")
    monkeypatch.setattr(_pdf_to_tf, "extract_pdf", fail)
    with pytest.raises(ValueError, match="forced PDF OCR"):
        _pdf_to_tf.convert_pdf_to_tf(str(PDF), tmp_path / "tf")
    assert not (tmp_path / "tf").exists()


def test_corpus_grade_reads_final_archived_page_stream(tmp_path, pinned_pdf_ocr):
    observations = []
    def provider(source, evidence):
        pages = evidence["converted_pages"]
        assert set(pages) == {"1", "2"}
        assert all("Unicode café" in text for text in pages.values())
        observations.append(pages)
        return {"source_sha256": evidence["source_sha256"],
                "snapshot_sha256": evidence["snapshot_sha256"],
                "score_percent": 75, "complete": True}
    output = run_conversion(source_path=PDF, work_dir=tmp_path / "work", source_format=SourceFormat.PDF,
                            output_path_for=lambda name: tmp_path / "book.corpus",
                            pdf_comparison_provider=provider)
    assert output.is_file() and len(observations) == 1
