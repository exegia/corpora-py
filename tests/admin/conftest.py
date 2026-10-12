"""Recorded real OCR output: unit/API tests never download models or run OCR."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def pinned_pdf_ocr(monkeypatch):
    from admin.converters import _pdf_to_tf
    from admin.parsers import pdf_ocr
    from admin.services import source_reliability

    payload = json.loads((Path(__file__).parent / "fixtures/cusx/docling-forced-ocr.json").read_text())

    def extract(source):
        # Real SDK data and checksums, with inference replaced only at its seam.
        return pdf_ocr.project_snapshot(source, payload["snapshot"], payload["provenance"], 2)

    monkeypatch.setattr(pdf_ocr, "extract_pdf", extract)
    monkeypatch.setattr(_pdf_to_tf, "extract_pdf", extract)
    monkeypatch.setattr(pdf_ocr, "check_ocr_runtime", lambda: None)
    # This fixture exercises transport of an independent assessment; the score
    # algorithm is tested separately against explicitly supplied references.
    monkeypatch.setattr(source_reliability, "configured_comparison", lambda source, evidence: {
        "source_sha256": evidence["source_sha256"], "snapshot_sha256": evidence["snapshot_sha256"],
        "score_percent": 75, "complete": True, "method": "test-independent-review", "mismatches": [],
    })
    return payload
