import json

import pytest
from admin.services import pdf_comparison as comparison


@pytest.fixture
def comparison_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CORPORA_PDF_COMPARISON_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("CORPORA_PDF_COMPARISON_PYTHON", "independent-python")
    monkeypatch.setenv("CORPORA_PDF_COMPARISON_MODELS", str(tmp_path / "models"))
    monkeypatch.setenv("CORPORA_PDF_COMPARISON_BINARY", str(tmp_path / "binary"))
    source = tmp_path / "book.pdf"
    source.write_bytes(b"original PDF revision")
    evidence = {
        "source_sha256": comparison.digest(source.read_bytes()),
        "snapshot_sha256": "sha256:docling-snapshot",
        "converted_pages": {"1": "One page.\n", "2": "Second page.\n"},
    }
    path = comparison.comparison_cache(source, "independent-python", tmp_path / "models", tmp_path / "binary")
    snapshot = {
        "source_sha256": evidence["source_sha256"],
        "lock_sha256": comparison.digest(comparison.LOCK.read_bytes()),
        "page_count": 2, "models": {"revision": "pinned-model"},
        "pages": {"1": {"text": "One page."}, "2": {"text": "Second page."}},
    }

    def save():
        path.write_bytes(comparison.encoded({
            "snapshot": snapshot,
            "snapshot_sha256": comparison.digest(comparison.encoded(snapshot)),
        }))

    save()
    return source, evidence, path, snapshot, save


def test_cached_independent_pixels_are_compared_with_final_output(comparison_cache, monkeypatch):
    source, evidence, _, _, _ = comparison_cache
    monkeypatch.setattr(comparison, "run_worker", lambda *_: pytest.fail("Completed pixel OCR must be reused"))
    result = comparison.automatic_comparison(source, evidence)
    assert result["score_percent"] == 100
    assert result["assessment_kind"] == "automatic-ocr-agreement"
    assert result["compared_pages"] == 2
    evidence["converted_pages"]["2"] = "Damaged output"
    altered = comparison.automatic_comparison(source, evidence)
    assert altered["score_percent"] < result["score_percent"]
    assert altered["mismatches"]
    assert altered["comparison_snapshot_sha256"] == result["comparison_snapshot_sha256"]


def test_tampered_independent_snapshot_cannot_pass(comparison_cache):
    source, evidence, path, _, _ = comparison_cache
    payload = json.loads(path.read_text())
    payload["snapshot"]["pages"]["1"]["text"] = "tampered"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="checksum mismatch"):
        comparison.automatic_comparison(source, evidence)


def test_partial_page_inventory_is_resumed_and_never_scored(comparison_cache, monkeypatch):
    source, evidence, _, snapshot, save = comparison_cache
    del snapshot["pages"]["2"]
    save()

    def incomplete(*args):
        raise ValueError("Independent visual OCR was incomplete")

    monkeypatch.setattr(comparison, "run_worker", incomplete)
    with pytest.raises(ValueError, match="incomplete"):
        comparison.automatic_comparison(source, evidence)


def test_missing_runtime_is_an_actionable_error(tmp_path, monkeypatch):
    monkeypatch.delenv("CORPORA_PDF_COMPARISON_PYTHON", raising=False)
    with pytest.raises(ValueError, match="runtime is not configured"):
        comparison.automatic_comparison(tmp_path / "source.pdf", {})


def test_export_uses_the_exact_completed_snapshot(comparison_cache):
    source, evidence, path, _, _ = comparison_cache
    result = comparison.automatic_comparison(source, evidence)
    payload, lock = comparison.export_comparison_evidence(source, result)
    assert payload == json.loads(path.read_text())
    assert comparison.digest(lock) == result["comparison_lock_sha256"]


def test_export_rejects_a_snapshot_changed_after_assessment(comparison_cache):
    source, evidence, _, snapshot, save = comparison_cache
    result = comparison.automatic_comparison(source, evidence)
    snapshot["pages"]["1"]["text"] = "changed after validation"
    save()
    with pytest.raises(ValueError, match="differs from the completed comparison"):
        comparison.export_comparison_evidence(source, result)
