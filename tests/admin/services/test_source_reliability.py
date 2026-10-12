import json
import zipfile
from pathlib import Path

import pytest
from admin.converters.cusx import convert_to_cusx
from admin.parsers.pdf_ocr import project_snapshot
from admin.parsers.schema import SourceFormat
from admin.services.conversion import CorpusValidationError, run_conversion
from admin.services.source_reliability import (
    assess_reliability,
    compare_verified_pages,
    configured_comparison,
    validate_pdf_source,
)

PDF = Path(__file__).parents[1] / "fixtures/cusx/outlined.pdf"


@pytest.mark.parametrize(
    "score,decision,passed,review",
    [
        (0, "loss", False, False),
        (49.9999, "loss", False, False),
        (50, "review", True, True),
        (90, "review", True, True),
        (90.0001, "pass", True, False),
        (100, "pass", True, False),
    ],
)
def test_exact_unrounded_boundaries(score, decision, passed, review):
    result = assess_reliability(score)
    assert (result["decision"], result["passed"], result["review_required"]) == (
        decision,
        passed,
        review,
    )


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -1, 101, True, "95"])
def test_nonfinite_or_invalid_scores_cannot_pass(score):
    with pytest.raises(ValueError):
        assess_reliability(score)


def test_incomplete_or_missing_comparison_is_unscored():
    assert assess_reliability(None)["decision"] == "unscored"
    assert not assess_reliability(100, complete=False)["passed"]


def test_canonical_greek_equivalence_preserves_source_spelling():
    result = compare_verified_pages({"1": "διδάσκαλον\n"}, {"1": "διδάσκαλον\n"})
    assert result["score_percent"] == 100
    assert result["mismatches"] == []


def test_english_cannot_hide_lost_hebrew_points_or_letters():
    prose = "Unchanged English prose. " * 100
    result = compare_verified_pages({"1": prose + "רוּחַ"}, {"1": prose + "wind"})
    assert result["dimension_scores"]["text"] > 99
    assert result["score_percent"] == 0
    assert result["mismatches"] and result["mismatches"][0]["page_number"] == 1


def test_output_only_script_noise_does_not_zero_an_english_reference():
    prose = "Unchanged English prose. " * 100
    result = compare_verified_pages({"1": prose + "I am in camp"}, {"1": prose + "Ι am תו (ΠΡ"})
    assert result["score_percent"] > 99
    assert set(result["dimension_scores"]) == {"text"}
    assert any("Ι" in mismatch["actual"] for mismatch in result["mismatches"])
    assert result["method"] == "verified-page-character-agreement/v2"


def test_source_script_on_later_page_still_controls_score():
    result = compare_verified_pages(
        {"1": "English page", "2": "רוּחַ"},
        {"1": "English page Ι", "2": "wind"},
    )
    assert result["score_percent"] == 0
    assert result["dimension_scores"]["hebrew"] == 0
    assert "greek" not in result["dimension_scores"]


def test_missing_page_never_scores_as_a_partial_success():
    with pytest.raises(ValueError, match="every converted PDF page"):
        compare_verified_pages({"1": "one", "2": "two"}, {"1": "one"})


def test_snapshot_tampering_and_source_revision_are_rejected(pinned_pdf_ocr, tmp_path):
    payload = pinned_pdf_ocr
    altered = json.loads(json.dumps(payload["snapshot"]))
    altered["blocks"][0]["text"] = "changed"
    with pytest.raises(ValueError, match="checksum"):
        project_snapshot(PDF, altered, payload["provenance"], 2)
    other = tmp_path / "other.pdf"
    other.write_bytes(PDF.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="different source"):
        project_snapshot(other, payload["snapshot"], payload["provenance"], 2)


@pytest.mark.parametrize("score,expect_pass", [(49, False), (50, True), (90, True), (91, True)])
def test_pipeline_enforces_source_review_policy(pinned_pdf_ocr, tmp_path, score, expect_pass):
    recorded = []

    def provider(source, evidence):
        assert source == PDF
        assert set(evidence["converted_pages"]) == {"1", "2"}
        return {
            "source_sha256": evidence["source_sha256"],
            "snapshot_sha256": evidence["snapshot_sha256"],
            "score_percent": score,
            "complete": True,
            "mismatches": [{"page_number": 1, "expected": "x", "actual": "y"}],
        }

    args = dict(
        source_path=PDF,
        work_dir=tmp_path / "work",
        source_format=SourceFormat.PDF,
        output_path_for=lambda name: tmp_path / "book.cusx",
        output_format="cusx",
        on_validation=recorded.append,
        pdf_comparison_provider=provider,
    )
    if expect_pass:
        assert run_conversion(**args).is_file()
    else:
        with pytest.raises(CorpusValidationError, match="another source format"):
            run_conversion(**args)
    report = recorded[0]["source_reliability"]
    assert report["score_percent"] == score and report["passed"] is expect_pass
    assert report["review_required"] is (50 <= score <= 90)


def test_provider_cannot_reuse_assessment_for_another_snapshot(pinned_pdf_ocr, tmp_path):
    archive = convert_to_cusx(
        PDF, tmp_path / "book.cusx", source_format=SourceFormat.PDF, name="Book"
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_pdf_source(
            PDF, archive, lambda source, evidence: {"score_percent": 100, "complete": True}
        )


def test_trusted_reference_must_include_visual_and_structure_review(tmp_path, monkeypatch):
    evidence = {
        "source_sha256": "sha256:" + "a" * 64,
        "snapshot_sha256": "sha256:" + "b" * 64,
        "converted_pages": {"1": "בְּרִית"},
    }
    monkeypatch.setenv("CORPORA_PDF_REFERENCE_DIR", str(tmp_path))
    path = tmp_path / ("a" * 64 + ".json")
    reference = {
        "source_sha256": evidence["source_sha256"],
        "verified_against": "visible-pdf-pages",
        "pages": {"1": "בְּרִית"},
        "structure_reviewed": False,
        "reviewed_snapshot_sha256": evidence["snapshot_sha256"],
    }
    path.write_text(json.dumps(reference))
    report = configured_comparison(PDF, evidence)
    assert report["score_percent"] == 100 and report["complete"] is False
    reference["structure_reviewed"] = True
    path.write_text(json.dumps(reference))
    assert configured_comparison(PDF, evidence)["complete"] is True


def test_missing_references_hold_acceptance(pinned_pdf_ocr, tmp_path, monkeypatch):
    # Restore the actual configured callback rather than the fixture assessment.
    from admin.services import source_reliability

    monkeypatch.setattr(source_reliability, "configured_comparison", configured_comparison)
    monkeypatch.delenv("CORPORA_PDF_REFERENCE_DIR", raising=False)
    archive = convert_to_cusx(
        PDF, tmp_path / "book.cusx", source_format=SourceFormat.PDF, name="Book"
    )
    assert validate_pdf_source(PDF, archive)["decision"] == "unscored"
    with zipfile.ZipFile(archive) as package:
        assert "assets/pdf/ocr/provenance.json" in package.namelist()


def test_locked_worker_rejects_changed_assets(monkeypatch, tmp_path):
    from admin.parsers import pdf_ocr_worker

    model = tmp_path / "model--test" / "weights.bin"
    model.parent.mkdir()
    model.write_bytes(b"verified")
    lock = tmp_path / "lock.json"
    lock.write_text(
        json.dumps(
            {
                "profile": "test",
                "packages": {"docling": "2.137.0"},
                "models": [
                    {
                        "repo": "model/test",
                        "revision": "fixed",
                        "files": [
                            {
                                "path": "weights.bin",
                                "bytes": 8,
                                "sha256": pdf_ocr_worker.digest(model).removeprefix("sha256:"),
                            }
                        ],
                    }
                ],
                "tessdata": {"files": []},
            }
        )
    )
    monkeypatch.setattr(pdf_ocr_worker, "LOCK_PATH", lock)
    monkeypatch.setattr(pdf_ocr_worker.importlib.metadata, "version", lambda name: "2.137.0")
    assert pdf_ocr_worker.check_runtime(tmp_path)["profile"] == "test"
    model.write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum mismatch"):
        pdf_ocr_worker.check_runtime(tmp_path)
    model.write_bytes(b"verified")
    monkeypatch.setattr(pdf_ocr_worker.importlib.metadata, "version", lambda name: "2.138.0")
    with pytest.raises(ValueError, match="requires docling==2.137.0"):
        pdf_ocr_worker.check_runtime(tmp_path)
