"""Pre-conversion source validation for `POST /convert` (issue #173).

Runs right after the upload lands on disk, before a job is submitted: sniff
the file's real type from its magic bytes, compare it against the declared
`source_format`, and refuse anything that cannot become a text corpus —
images, audio/video, non-zip archives, unknown binary, and PDFs with no
extractable text layer (classified via `pdf_inspector`, the same library
the converter routes through — issue #175). Failing here turns a
minutes-long guaranteed-to-fail background job into an immediate 422 whose
detail is the full `UploadValidationReport`.

Detection is deliberately family-level ("pdf", "zip", "xml", "html",
"text", …), not format-level: magic bytes can tell a PDF from a ZIP, but
not an EPUB from a TEI ZIP (both are ZIPs) or TEI from generic XML — the
parsers own that distinction and fail fast enough on their own. Text
families cross-accept (declared `html` with no doctype sniffs as "text");
what gets rejected is a *structural* mismatch (declared `pdf`, got a ZIP)
or a non-convertible family.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..parsers.schema import SourceFormat

logger = logging.getLogger(__name__)

# How much of the file the sniffers get to see. Magic bytes live in the
# first handful; the rest is for the text/markup heuristics.
_SNIFF_BYTES = 4096

# Families with no text to extract -- never convertible, whatever was declared.
_NON_CONVERTIBLE = {
    "image": "an image",
    "audio": "an audio file",
    "video": "a video file",
    "archive": "a compressed archive (only ZIP-based uploads are supported)",
    "binary": "unrecognized binary data",
}

# Detected families each declared format accepts. The three text-ish
# families cross-accept: a doctype-less HTML fragment sniffs as "text", a
# TEI document as "xml" -- the parser is the authority past this point.
_TEXTUAL = frozenset({"text", "html", "xml"})
_ACCEPTED: dict[SourceFormat, frozenset[str]] = {
    SourceFormat.PDF: frozenset({"pdf"}),
    SourceFormat.EPUB: frozenset({"zip"}),
    SourceFormat.TF_ZIP: frozenset({"zip"}),
    SourceFormat.TEI_ZIP: frozenset({"zip"}),
    SourceFormat.HTML: _TEXTUAL,
    SourceFormat.XML: _TEXTUAL,
    SourceFormat.TEI: _TEXTUAL,
    SourceFormat.PLAIN: _TEXTUAL,
}

_MAGIC_FAMILIES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"II*\x00", "image"),
    (b"MM\x00*", "image"),
    (b"ID3", "audio"),
    (b"OggS", "audio"),
    (b"fLaC", "audio"),
    (b"\xff\xfb", "audio"),
    (b"\x1f\x8b", "archive"),
    (b"7z\xbc\xaf", "archive"),
    (b"Rar!", "archive"),
    (b"BZh", "archive"),
)


@dataclass
class UploadValidationReport:
    """What the gate found; serialized wholesale into the 422 detail."""

    declared_format: str
    detected_format: str
    convertible: bool = True
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # `pdf_inspector` classification payload, only for declared-PDF uploads:
    # pdf_type / confidence / page_count / pages_needing_ocr (1-based).
    pdf: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_format": self.declared_format,
            "detected_format": self.detected_format,
            "convertible": self.convertible,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "pdf": self.pdf,
        }


def _detect_family(head: bytes) -> str:
    """Best-effort family from the first `_SNIFF_BYTES` of the upload."""
    if not head:
        return "empty"
    for magic, family in _MAGIC_FAMILIES:
        if head.startswith(magic):
            return family
    if head.startswith(b"RIFF") and len(head) >= 12:
        riff_type = head[8:12]
        if riff_type == b"WAVE":
            return "audio"
        if riff_type == b"WEBP":
            return "image"
        if riff_type.startswith(b"AVI"):
            return "video"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "video"

    if b"\x00" in head:
        return "binary"
    try:
        text = head.decode("utf-8", errors="strict" if len(head) < _SNIFF_BYTES else "ignore")
    except UnicodeDecodeError:
        return "binary"
    stripped = text.lstrip("﻿").lstrip()
    lowered = stripped[:256].lower()
    if lowered.startswith("<!doctype html") or "<html" in lowered:
        return "html"
    if stripped.startswith("<"):
        return "xml"
    return "text"


def _classify_pdf(path: Path, report: UploadValidationReport) -> None:
    """Attach `pdf_inspector`'s verdict; reject PDFs with no text layer."""
    import pdf_inspector

    try:
        classification = pdf_inspector.classify_pdf(str(path))
    except ValueError as exc:
        report.convertible = False
        report.reasons.append(f"PDF could not be read: {exc}")
        return
    except Exception:
        # The inspector failing is not the upload's fault -- let the
        # conversion route decide (it has a pypdf fallback, issue #175).
        logger.warning("pdf_inspector classification failed for %s", path, exc_info=True)
        return

    skipped = sorted(page + 1 for page in classification.pages_needing_ocr or [])
    report.pdf = {
        "pdf_type": classification.pdf_type,
        "confidence": classification.confidence,
        "page_count": classification.page_count,
        "pages_needing_ocr": skipped,
    }
    if classification.pdf_type in ("scanned", "image_based"):
        report.convertible = False
        report.reasons.append(
            f"PDF has no extractable text layer (classified "
            f"'{classification.pdf_type}', {classification.page_count} pages); "
            "OCR is required before conversion"
        )
    elif classification.pdf_type == "mixed" and skipped:
        pages = ", ".join(str(page) for page in skipped)
        report.warnings.append(
            f"{len(skipped)} page(s) need OCR and will be skipped: {pages}"
        )


def validate_upload(path: Path, declared: SourceFormat) -> UploadValidationReport:
    """Sniff `path` and decide whether conversion as `declared` can work.

    Never raises for a bad upload -- the verdict (and why) is the report;
    the caller turns `convertible=False` into a 422 carrying `to_dict()`.
    """
    with path.open("rb") as fh:
        head = fh.read(_SNIFF_BYTES)
    detected = _detect_family(head)
    report = UploadValidationReport(
        declared_format=declared.value, detected_format=detected
    )

    if detected == "empty":
        report.convertible = False
        report.reasons.append("Uploaded file is empty")
        return report
    if detected in _NON_CONVERTIBLE:
        report.convertible = False
        report.reasons.append(
            f"Upload was detected as {_NON_CONVERTIBLE[detected]}, which "
            "cannot be converted to a text corpus"
        )
        return report

    accepted = _ACCEPTED.get(declared)
    if accepted is not None and detected not in accepted:
        report.convertible = False
        report.reasons.append(
            f"Declared source_format '{declared.value}' but the upload was "
            f"detected as '{detected}'"
        )
        return report

    if declared is SourceFormat.PDF:
        _classify_pdf(path, report)
    return report
