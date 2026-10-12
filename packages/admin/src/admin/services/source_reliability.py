"""Source comparison contract and the PDF conversion acceptance policy.

An archive checksum or an OCR confidence is never a source reliability score.
The comparison provider must inspect the source independently and bind its
assessment to both the original PDF and the exact OCR snapshot being packaged.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import unicodedata
import zipfile
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ComparisonProvider = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _script(text: str, name: str) -> str:
    result = []
    active = False
    for character in unicodedata.normalize("NFD", text):
        category = unicodedata.category(character)
        if category.startswith("L"):
            active = unicodedata.name(character, "").startswith(name)
        elif not category.startswith("M"):
            active = False
        if active and category[0] in "LM":
            result.append(character)
    return "".join(result)


def compare_verified_pages(expected: dict[str, str], actual: dict[str, str]) -> dict[str, Any]:
    """Character agreement with canonical equivalence, including marks/order.

    Score is the lowest of whole-text agreement and the Hebrew/Greek dimensions
    present in the reference. Output-only script errors still lower whole-text
    agreement, but cannot make an English reference score zero. English
    prose therefore cannot hide damaged source language examples. This is a declared
    agreement metric against supplied verified references, not model confidence
    or a statistical probability of correctness.
    """
    if not expected or set(expected) != set(actual):
        raise ValueError("Verified source references must cover every converted PDF page")
    measures = {"text": [0, 0], "hebrew": [0, 0], "greek": [0, 0]}
    reference_dimensions = {"text"}
    mismatches = []
    for page in sorted(expected, key=int):
        if not isinstance(expected[page], str) or not isinstance(actual[page], str):
            raise ValueError("Verified PDF page references must contain text strings")
        before = unicodedata.normalize("NFD", expected[page])
        after = unicodedata.normalize("NFD", actual[page])
        matcher = SequenceMatcher(None, before, after, autojunk=False)
        for kind, i, j, a, b in matcher.get_opcodes():
            if kind != "equal":
                mismatches.append(
                    {
                        "page_number": int(page),
                        "kind": kind,
                        "reference_range": [i, j],
                        "converted_range": [a, b],
                        "expected": before[i:j],
                        "actual": after[a:b],
                        "offset_stream": "unicode-scalar/NFD",
                    }
                )
        for kind in measures:
            left, right = (
                (before, after)
                if kind == "text"
                else (_script(before, kind.upper()), _script(after, kind.upper()))
            )
            if left:
                reference_dimensions.add(kind)
            matches = sum(
                block.size
                for block in SequenceMatcher(
                    None, left, right, autojunk=False
                ).get_matching_blocks()
            )
            measures[kind][0] += 2 * matches
            measures[kind][1] += len(left) + len(right)
    scores = {
        key: 100 * matched / total
        for key, (matched, total) in measures.items()
        if total and key in reference_dimensions
    }
    if not scores:
        raise ValueError("Verified PDF references contain no text to assess")
    return {
        "score_percent": min(scores.values()),
        "dimension_scores": scores,
        "mismatches": mismatches,
        "method": "verified-page-character-agreement/v2",
        "normalization": "NFD canonical equivalence; whitespace/order/marks compared",
    }


def configured_comparison(source: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    """Read trusted reviewer references keyed by the original source digest.

    This directory is server configuration, never derived from an uploaded
    document, and references are not synthesized from the PDF's hidden layer.
    A visual review provider can replace this callback through run_conversion.
    """
    directory = os.environ.get("CORPORA_PDF_REFERENCE_DIR")
    filename = evidence["source_sha256"].removeprefix("sha256:") + ".json"
    if not directory or not (Path(directory) / filename).is_file():
        if os.environ.get("CORPORA_PDF_COMPARISON_PYTHON"):
            from .pdf_comparison import automatic_comparison
            return automatic_comparison(source, evidence)
        return {
            "score_percent": None,
            "complete": False,
            "source_sha256": evidence["source_sha256"],
            "snapshot_sha256": evidence["snapshot_sha256"],
            "method": "verified-reference-unavailable",
        }
    reference = json.loads((Path(directory) / filename).read_text())
    if (
        reference.get("source_sha256") != evidence["source_sha256"]
        or reference.get("verified_against") != "visible-pdf-pages"
    ):
        raise ValueError("PDF reference has no verified visual-source provenance")
    actual = evidence["converted_pages"]
    if actual is None:
        raise ValueError("Final converted PDF text is unavailable for source comparison")
    report = compare_verified_pages(reference["pages"], actual)
    report.update(
        source_sha256=evidence["source_sha256"],
        snapshot_sha256=evidence["snapshot_sha256"],
        reference_sha256="sha256:"
        + hashlib.sha256((Path(directory) / filename).read_bytes()).hexdigest(),
        complete=reference.get("structure_reviewed") is True
        and reference.get("reviewed_snapshot_sha256") == evidence["snapshot_sha256"],
    )
    return report


def assess_reliability(
    score_percent: float | None, *, complete: bool = True, mismatches: list[dict] | None = None
) -> dict[str, Any]:
    """Apply unrounded thresholds. Exactly 50 and exactly 90 require review."""
    if score_percent is not None and (
        isinstance(score_percent, bool)
        or not isinstance(score_percent, (int, float))
        or not math.isfinite(score_percent)
        or not 0 <= score_percent <= 100
    ):
        raise ValueError("Source reliability must be a finite percentage between 0 and 100")
    if score_percent is None or not complete:
        decision, passed, review = "unscored", False, True
        message = "Source comparison is incomplete; conversion reliability has not been established"
    elif score_percent < 50:
        decision, passed, review = "loss", False, False
        message = "Conversion lost too much source content. Try another source format, such as EPUB or HTML"
    elif score_percent <= 90:
        decision, passed, review = "review", True, True
        message = "Conversion passed with review required; inspect mismatches and manually edit the result"
    else:
        decision, passed, review = "pass", True, False
        message = "Conversion passed source reliability validation"
    return {
        "score_percent": score_percent,
        "decision": decision,
        "passed": passed,
        "review_required": review,
        "comparison_complete": complete and score_percent is not None,
        "mismatches": mismatches or [],
        "message": message,
        "thresholds": {"loss_below": 50, "review_through": 90},
    }


def validate_pdf_source(
    source: Path, archive: Path, provider: ComparisonProvider | None = None
) -> dict[str, Any]:
    """Compare the final converted page stream, rather than confidence metadata."""
    with zipfile.ZipFile(archive) as package:
        if archive.suffix == ".cusx":
            provenance = json.loads(package.read("assets/pdf/ocr/provenance.json"))
            snapshot = json.loads(package.read("assets/pdf/ocr/snapshot.json"))
            manifest = json.loads(package.read("manifest.json"))
            converted_pages = {
                str(doc["source"]["page_number"]): json.loads(package.read(doc["snapshot"]))["text"]
                for doc in manifest["documents"]
            }
        else:
            provenance = json.loads(package.read("corpora/pdf-ocr/provenance.json"))
            snapshot = json.loads(package.read("corpora/pdf-ocr/snapshot.json"))
            # Read the actual archived TF stream; never score a surrogate
            # pre-conversion snapshot as if it were the finished conversion.
            import tempfile

            from tf.fabric import Fabric

            with tempfile.TemporaryDirectory(prefix="pdf-reliability-") as directory:
                root = Path(directory)
                for member in package.namelist():
                    if member.startswith("corpora/") and member.endswith(".tf"):
                        name = member.removeprefix("corpora/")
                        if "/" in name or "\\" in name:
                            raise ValueError("Unexpected nested TF evidence member")
                        (root / name).write_bytes(package.read(member))
                api = Fabric(locations=str(root), silent="deep").loadAll(silent="deep")
                if not api:
                    raise ValueError("Converted PDF text could not be loaded for source comparison")
                converted_pages = {
                    str(api.F.page_number.v(node)): "".join(
                        (api.F.text.v(slot) or "") + (api.F.after.v(slot) or "")
                        for slot in api.E.oslots.s(node)
                    )
                    for node in api.F.otype.s("page")
                }
    source_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    encoded = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    if (
        provenance["source_sha256"] != source_hash
        or provenance["snapshot_sha256"] != "sha256:" + hashlib.sha256(encoded).hexdigest()
    ):
        raise ValueError("PDF reliability evidence revision or snapshot checksum mismatch")
    evidence = {
        "source_sha256": source_hash,
        "snapshot_sha256": provenance["snapshot_sha256"],
        "snapshot": snapshot,
        "converted_pages": converted_pages,
        "archive": archive,
        "provenance": provenance,
    }
    comparison = (provider or configured_comparison)(source, evidence)
    if comparison is not None:
        if (
            comparison.get("source_sha256") != source_hash
            or comparison.get("snapshot_sha256") != provenance["snapshot_sha256"]
        ):
            raise ValueError("Source comparison does not match the converted PDF revision")
        report = assess_reliability(
            comparison.get("score_percent"),
            complete=comparison.get("complete") is True,
            mismatches=comparison.get("mismatches", []),
        )
        report["method"] = comparison.get("method", "independent-source-comparison")
        for field in ("dimension_scores", "normalization", "reference_sha256", "assessment_kind",
                      "comparison_engine", "comparison_snapshot_sha256", "comparison_lock_sha256",
                      "comparison_model_revision", "compared_pages"):
            if field in comparison:
                report[field] = comparison[field]
    else:
        report = assess_reliability(None, complete=False)
    if report.get("assessment_kind") == "automatic-ocr-agreement":
        report["message"] += ". Score estimates agreement between independent visual OCR and converted text; it is not a probability of source accuracy"
    report.update(
        source_sha256=source_hash,
        snapshot_sha256=provenance["snapshot_sha256"],
        converter=provenance["profile"],
        converter_version=provenance.get("packages", {}).get("docling"),
        lock_sha256=provenance.get("lock_sha256"),
    )
    return report
