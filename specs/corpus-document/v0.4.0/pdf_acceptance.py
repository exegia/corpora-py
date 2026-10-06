"""Atomic PDF ingestion decision over explicit quality assessments.

This is a decision checker, not an OCR engine or universal legibility scorer.
Satisfactory/blank assessments require independent evidence supplied by the evaluator.
"""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent


def decide(
    source_sha256,
    source_page_count,
    scope,
    assessments,
    ocr_used=False,
    extraction_failed=False,
    candidate_sha256=None,
):
    issues = []
    if extraction_failed or source_page_count == 0:
        issues.append(
            {
                "code": "extraction-failed",
                "detail": "Source parsing/recovery failed or yielded no evaluable pages",
            }
        )
    indices = [a["pageIndex"] for a in assessments]
    if len(indices) != len(set(indices)) or any(i < 0 or i >= source_page_count for i in indices):
        issues.append(
            {
                "code": "invalid-page-coverage",
                "detail": "Duplicate or out-of-source page assessment",
            }
        )
    for page in assessments:
        index = page["pageIndex"]
        if page["content"] == "unreadable":
            issues.append(
                {
                    "code": "insufficient-content",
                    "pageIndex": index,
                    "detail": "Content recovery is insufficient; reject the entire import",
                }
            )
        if page["readingOrder"] == "material-failure":
            issues.append(
                {
                    "code": "material-reading-order-failure",
                    "pageIndex": index,
                    "detail": "Material source reading order remains incorrect",
                }
            )
    if scope == "whole-document" and set(indices) != set(range(source_page_count)):
        issues.append(
            {
                "code": "missing-pages",
                "detail": "Whole-document evaluation did not cover every source page",
            }
        )
    fatal = bool(issues)
    if candidate_sha256 is None:
        issues.append(
            {
                "code": "candidate-unbound",
                "detail": "Quality decision must bind the exact normalized candidate before acceptance",
            }
        )
    if scope != "whole-document":
        issues.append(
            {
                "code": "bounded-sample-only",
                "detail": "A bounded sample cannot certify an entire PDF",
            }
        )
    for page in assessments:
        if page["content"] in ("satisfactory", "blank-confirmed") and not page["evidence"]:
            issues.append(
                {
                    "code": "missing-quality-evidence",
                    "pageIndex": page["pageIndex"],
                    "detail": "Legibility or legitimate blankness lacks evaluator evidence",
                }
            )
        if page["content"] == "unverified" or (
            page["content"] != "blank-confirmed" and page["readingOrder"] == "unverified"
        ):
            issues.append(
                {
                    "code": "quality-unverified",
                    "pageIndex": page["pageIndex"],
                    "detail": "Extraction success is not independently verified quality",
                }
            )
    status = "rejected" if fatal else "pending-review" if issues else "accepted"
    result = {
        "specVersion": "0.4.0",
        "policyId": "urn:corpora:pdf-acceptance:0.4.0",
        "format": "pdf",
        "sourceSha256": source_sha256,
        "candidateSha256": candidate_sha256,
        "sourcePageCount": source_page_count,
        "scope": scope,
        "ocrUsed": ocr_used,
        "extractionFailed": extraction_failed,
        "assessments": assessments,
        "status": status,
        "issues": issues,
    }
    Draft202012Validator(
        json.loads((ROOT / "ingestion-decision.schema.json").read_text())
    ).validate(result)
    return result


def document_digest(document):
    return hashlib.sha256(
        json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def bind(document, decision):
    return decide(
        decision["sourceSha256"],
        decision["sourcePageCount"],
        decision["scope"],
        decision["assessments"],
        decision["ocrUsed"],
        decision["extractionFailed"],
        document_digest(document),
    )


def artifact(document, decision):
    """Accepted output exists only for an accepted, whole-document decision."""
    recomputed = decide(
        decision["sourceSha256"],
        decision["sourcePageCount"],
        decision["scope"],
        decision["assessments"],
        decision["ocrUsed"],
        decision["extractionFailed"],
        decision["candidateSha256"],
    )
    if recomputed != decision:
        raise ValueError("Decision does not match its assessment evidence")
    source_assets = {a["sha256"] for a in document.get("assets", [])}
    if decision["sourceSha256"] not in source_assets:
        raise ValueError("Decision is not bound to a document source asset")
    if decision["status"] == "accepted":
        if decision["candidateSha256"] != document_digest(document):
            raise ValueError("Candidate differs from the quality decision's bound graph")
        source_ids = {
            a["id"] for a in document["assets"] if a["sha256"] == decision["sourceSha256"]
        }
        page_indices = [
            int(source["value"])
            for node in document.get("nodes", [])
            if node["type"] == "core:page"
            for source in node.get("sourceIds", [])
            if source["assetId"] in source_ids and source["value"].isdigit()
        ]
        if sorted(page_indices) != list(range(decision["sourcePageCount"])):
            raise ValueError(
                "Mapped PDF page coverage does not match the accepted whole-document decision"
            )
        return {
            "artifactKind": "acceptedImportCandidate",
            "decision": decision,
            "document": document,
        }
    return {
        "artifactKind": "unacceptedDiagnostic",
        "decision": decision,
        "diagnosticDocument": document,
    }
