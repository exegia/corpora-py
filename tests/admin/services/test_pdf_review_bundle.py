import json
import zipfile
from pathlib import Path

import pytest
from admin.converters.cusx import convert_to_cusx, digest, encoded
from admin.converters.cusx_package import validate_package
from admin.converters.cusx_pdf_review import LOCK, REPORT, SNAPSHOT, bundle_pdf_review
from admin.parsers.schema import SourceFormat
from admin.services.conversion import run_conversion
from admin.services.source_reliability import validate_pdf_source

PDF = Path(__file__).parents[1] / "fixtures/cusx/outlined.pdf"


@pytest.fixture
def review_package(tmp_path, pinned_pdf_ocr):
    archive = convert_to_cusx(PDF, tmp_path / "book.cusx", source_format=SourceFormat.PDF, name="Book")
    report = validate_pdf_source(PDF, archive)
    lock = b'{"profile":"test-independent-ocr"}'
    with zipfile.ZipFile(archive) as package:
        manifest = json.loads(package.read("manifest.json"))
        snapshot = {
            "source_sha256": report["source_sha256"], "lock_sha256": digest(lock),
            "page_count": len(manifest["documents"]),
            "pages": {
                str(doc["source"]["page_number"]): {"text": json.loads(package.read(doc["snapshot"]))["text"]}
                for doc in manifest["documents"]
            },
        }
    payload = {"snapshot": snapshot, "snapshot_sha256": digest(encoded(snapshot))}
    report.update(
        score_percent=75, decision="review", passed=True, review_required=True,
        comparison_complete=True, assessment_kind="automatic-ocr-agreement",
        comparison_snapshot_sha256=payload["snapshot_sha256"],
        comparison_lock_sha256=digest(lock), compared_pages=2,
        mismatches=[{"page_number": 1, "expected": "רוּחַ", "actual": "רוח"}],
    )
    return archive, report, payload, lock


def test_evidence_is_portable_and_existing_document_bytes_are_unchanged(review_package, monkeypatch):
    archive, report, payload, lock = review_package
    with zipfile.ZipFile(archive) as package:
        original = {name: package.read(name) for name in package.namelist() if name != "manifest.json"}
    bundled, summary = bundle_pdf_review(archive, report, independent=payload, lock=lock)
    assert summary["valid"] and summary["source_reliability"] == bundled
    assert summary["stats"]["assets"] == 5 + 3  # fixture PDF source, image, OCR evidence and three review assets
    with zipfile.ZipFile(archive) as package:
        assert json.loads(package.read(REPORT)) == bundled
        assert json.loads(package.read(SNAPSHOT)) == payload
        assert package.read(LOCK) == lock
        manifest = json.loads(package.read("manifest.json"))
        for path in (REPORT, SNAPSHOT, LOCK):
            assert path in manifest["assets"]
            assert manifest["files"][path] == digest(package.read(path))
        for path, content in original.items():
            assert package.read(path) == content
    monkeypatch.delenv("CORPORA_PDF_COMPARISON_PYTHON", raising=False)
    offline = validate_package(archive)
    assert offline["checks"]["pdf_review_evidence"]
    assert offline["source_reliability"]["score_percent"] == 75
    assert offline["source_reliability"]["mismatches"] == report["mismatches"]


@pytest.mark.parametrize("changed_field", ["source", "documents"])
def test_rehashed_but_wrong_revision_report_is_rejected(review_package, changed_field):
    archive, report, payload, lock = review_package
    bundle_pdf_review(archive, report, independent=payload, lock=lock)
    with zipfile.ZipFile(archive) as package:
        members = {name: package.read(name) for name in package.namelist()}
    changed = json.loads(members[REPORT])
    if changed_field == "source":
        changed["source_sha256"] = "sha256:" + "f" * 64
    else:
        changed["bundle"]["documents"]["documents/0001.usx"] = "sha256:" + "f" * 64
    members[REPORT] = encoded(changed)
    manifest = json.loads(members["manifest.json"])
    manifest["files"][REPORT] = digest(members[REPORT])
    members["manifest.json"] = encoded(manifest)
    with zipfile.ZipFile(archive, "w") as package:
        for name, data in members.items():
            package.writestr(name, data)
    result = validate_package(archive)
    assert not result["valid"]
    assert ("review report source revision mismatch" if changed_field == "source"
            else "review report points to incorrect bundle members") in result["reasons"][0]


def test_partial_independent_snapshot_never_replaces_existing_archive(review_package):
    archive, report, payload, lock = review_package
    before = archive.read_bytes()
    del payload["snapshot"]["pages"]["2"]
    payload["snapshot_sha256"] = digest(encoded(payload["snapshot"]))
    report["comparison_snapshot_sha256"] = payload["snapshot_sha256"]
    with pytest.raises(ValueError, match="page inventory is incomplete"):
        bundle_pdf_review(archive, report, independent=payload, lock=lock)
    assert archive.read_bytes() == before


def test_app_pipeline_bundles_the_assessment_before_download(review_package, tmp_path, monkeypatch):
    _, expected, payload, lock = review_package
    monkeypatch.setattr("admin.services.pdf_comparison.export_comparison_evidence", lambda *_: (payload, lock))
    summaries = []
    result = run_conversion(
        source_path=PDF, work_dir=tmp_path / "work", source_format=SourceFormat.PDF,
        output_path_for=lambda _: tmp_path / "export.cusx", output_format="cusx",
        pdf_comparison_provider=lambda *_: dict(expected, complete=True),
        on_validation=summaries.append,
    )
    with zipfile.ZipFile(result) as package:
        bundled = json.loads(package.read(REPORT))
        assert bundled == summaries[0]["source_reliability"]
        assert SNAPSHOT in package.namelist()
    assert bundled["decision"] == "review"
    assert summaries[0]["valid"]
