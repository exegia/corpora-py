"""Portable PDF review assets within the existing C-USX asset inventory."""

import json
import math
import uuid
import zipfile
from pathlib import Path

from .cusx import digest, encoded

PROFILE = "corpora-pdf-review/1"
REPORT = "assets/pdf/review/reliability.json"
SNAPSHOT = "assets/pdf/review/independent-ocr.json"
LOCK = "assets/pdf/review/independent-ocr.lock.json"


def check_pdf_review(manifest: dict, members: dict[str, bytes]) -> None:
    """Check review evidence without requiring an OCR runtime or local cache."""
    if not any(path in members for path in (REPORT, SNAPSHOT, LOCK)):
        return
    if manifest["source"]["format"] != "pdf":
        raise ValueError("PDF review evidence requires a PDF source")
    report = json.loads(members[REPORT])
    bundle = {
        "profile": PROFILE, "report": REPORT,
        "documents": {doc["path"]: doc["identity"]["revision"] for doc in manifest["documents"]},
    }
    if report["source_sha256"] != manifest["source"]["revision"]:
        raise ValueError("PDF review report source revision mismatch")
    provenance = json.loads(members["assets/pdf/ocr/provenance.json"])
    docling = json.loads(members["assets/pdf/ocr/snapshot.json"])
    if (
        report["snapshot_sha256"] != digest(encoded(docling))
        or report["snapshot_sha256"] != provenance["snapshot_sha256"]
        or report["source_sha256"] != provenance["source_sha256"]
    ):
        raise ValueError("PDF review report conversion snapshot mismatch")
    score = report["score_percent"]
    if score is not None and (
        isinstance(score, bool) or not isinstance(score, (int, float))
        or not math.isfinite(score) or not 0 <= score <= 100
    ):
        raise ValueError("Invalid bundled PDF reliability score")
    decision = (
        "unscored" if score is None or not report["comparison_complete"]
        else "loss" if score < 50 else "review" if score <= 90 else "pass"
    )
    if (
        report["decision"] != decision
        or report["passed"] is not (decision in ("review", "pass"))
        or report["review_required"] is not (decision in ("review", "unscored"))
    ):
        raise ValueError("Bundled PDF reliability decision differs from its score")
    pages = {str(doc["source"]["page_number"]) for doc in manifest["documents"]}
    if not isinstance(report["mismatches"], list) or any(
        str(item["page_number"]) not in pages
        or not isinstance(item["expected"], str) or not isinstance(item["actual"], str)
        for item in report["mismatches"]
    ):
        raise ValueError("Invalid bundled PDF mismatches")
    if report.get("assessment_kind") == "automatic-ocr-agreement":
        bundle.update(independent_snapshot=SNAPSHOT, independent_lock=LOCK)
        payload = json.loads(members[SNAPSHOT])
        snapshot = payload["snapshot"]
        if (
            digest(encoded(snapshot)) != payload["snapshot_sha256"]
            or payload["snapshot_sha256"] != report["comparison_snapshot_sha256"]
            or snapshot["source_sha256"] != report["source_sha256"]
        ):
            raise ValueError("Bundled independent OCR snapshot checksum or source mismatch")
        if (
            digest(members[LOCK]) != snapshot["lock_sha256"]
            or snapshot["lock_sha256"] != report["comparison_lock_sha256"]
        ):
            raise ValueError("Bundled independent OCR lock checksum mismatch")
        if (
            set(snapshot["pages"]) != pages
            or snapshot["page_count"] != len(pages)
            or report["compared_pages"] != len(pages)
        ):
            raise ValueError("Bundled independent OCR page inventory is incomplete")
    elif SNAPSHOT in members or LOCK in members:
        raise ValueError("Independent OCR evidence lacks an automatic comparison report")
    if report["bundle"] != bundle:
        raise ValueError("PDF review report points to incorrect bundle members")


def bundle_pdf_review(
    archive: Path, report: dict, *, independent: dict | None = None, lock: bytes | None = None
) -> tuple[dict, dict]:
    """Atomically attach review assets and revalidate the complete package."""
    from .cusx_package import _check_package, validate_package

    manifest, members = _check_package(archive)
    bundled = dict(report)
    bundled["bundle"] = {
        "profile": PROFILE, "report": REPORT,
        "documents": {doc["path"]: doc["identity"]["revision"] for doc in manifest["documents"]},
    }
    if report.get("assessment_kind") == "automatic-ocr-agreement":
        if independent is None or lock is None:
            raise ValueError("Complete independent OCR evidence is required for C-USX export")
        bundled["bundle"].update(independent_snapshot=SNAPSHOT, independent_lock=LOCK)
        members[SNAPSHOT] = encoded(independent)
        members[LOCK] = lock
    members[REPORT] = encoded(bundled)
    manifest["assets"] = sorted(path for path in members if path.startswith("assets/"))
    manifest["files"] = {path: digest(data) for path, data in members.items()}
    check_pdf_review(manifest, members)
    temporary = archive.with_name(archive.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("manifest.json", encoded(manifest))
            for path, data in members.items():
                output.writestr(path, data)
        summary = validate_package(temporary)
        if not summary["valid"]:
            raise ValueError("; ".join(summary["reasons"]))
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    summary["corpus"] = archive.stem
    return bundled, summary
