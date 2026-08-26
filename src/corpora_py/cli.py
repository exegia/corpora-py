"""``corpora`` — terminal CLI over the conversion pipeline (issue #188).

Runs the exact same pipeline as ``POST /convert`` — upload gate →
parse → Text-Fabric → ``.cfm`` → ``.corpus`` → validation gate — but
locally and synchronously, with no server, jobs, or transport involved:
everything goes through the transport-free
`admin.services.conversion.run_conversion` seam. This is the
super-admin's local conversion path (see issues #185/#187/#188 — the
hosted poll-driven transport is being retired in favor of local
conversion).

Usage::

    corpora convert mobydick.epub --name "Moby Dick" -o mobydick.corpus
    corpora convert dataset.zip --format tf_zip
    corpora validate mobydick.corpus

Exit codes: 0 success; 1 conversion/validation failure; 2 bad usage
(unreadable source, unknown format, upload gate rejection, refusing to
overwrite).
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
import tempfile
from pathlib import Path

from admin.parsers.schema import CorpusCategory, SourceFormat
from admin.services.conversion import (
    ConversionError,
    CorpusValidationError,
    run_conversion,
    validate_archive,
)
from admin.services.upload_validation import validate_upload

# Extension → format for the unambiguous cases. `.zip` is deliberately
# absent: magic bytes and extensions can't tell a Text-Fabric dataset ZIP
# from a TEI-document ZIP, so ZIP sources must pass an explicit --format.
_EXTENSION_FORMATS: dict[str, SourceFormat] = {
    ".epub": SourceFormat.EPUB,
    ".html": SourceFormat.HTML,
    ".htm": SourceFormat.HTML,
    ".xhtml": SourceFormat.HTML,
    ".xml": SourceFormat.XML,
    ".tei": SourceFormat.TEI,
    ".pdf": SourceFormat.PDF,
    ".txt": SourceFormat.PLAIN,
    ".text": SourceFormat.PLAIN,
    ".md": SourceFormat.PLAIN,
    ".markdown": SourceFormat.PLAIN,
}


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _slugify(name: str) -> str:
    """Kebab-case a display name for the default output filename.

    Mirrors the server's result-filename slugging (`jobs._slugify`) without
    importing `jobs` — that module spins up the `JobManager` thread pool at
    import time, which a one-shot CLI has no use for.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _infer_format(source: Path, declared: str | None) -> SourceFormat:
    if declared:
        return SourceFormat(declared)
    suffix = source.suffix.lower()
    if suffix == ".zip":
        raise SystemExit(
            "error: a .zip source is ambiguous — pass --format tf_zip "
            "(a Text-Fabric dataset) or --format tei_zip (TEI documents)."
        )
    inferred = _EXTENSION_FORMATS.get(suffix)
    if inferred is None:
        known = ", ".join(sorted(_EXTENSION_FORMATS))
        raise SystemExit(
            f"error: cannot infer a source format from '{source.name}' — "
            f"pass --format (recognized extensions: {known}, .zip with an "
            "explicit --format)."
        )
    return inferred


def _print_validation(summary: dict) -> None:
    verdict = "valid" if summary.get("valid") else "INVALID"
    _log(f"Validation: {verdict}")
    stats = summary.get("stats") or {}
    if stats:
        rendered = ", ".join(f"{key}={value}" for key, value in stats.items())
        _log(f"  stats: {rendered}")
    for reason in summary.get("reasons") or []:
        _log(f"  reason: {reason}")


def _cmd_convert(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    if not source.is_file():
        raise SystemExit(f"error: source file not found: {source}")
    source_format = _infer_format(source, args.format)

    # The same pre-conversion gate as POST /convert (issue #173): reject
    # obviously non-convertible bytes before spending minutes converting.
    report = validate_upload(source, source_format)
    for warning in report.warnings:
        _log(f"warning: {warning}")
    if not report.convertible:
        for reason in report.reasons:
            _log(f"error: {reason}")
        raise SystemExit(2)

    category = CorpusCategory(args.category) if args.category else None

    def output_path_for(display_name: str) -> Path:
        if args.output:
            path = Path(args.output).expanduser()
        else:
            stem = _slugify(display_name) or _slugify(source.stem) or "corpus"
            path = Path.cwd() / f"{stem}.corpus"
        if path.exists() and not args.force:
            raise SystemExit(
                f"error: {path} already exists — pass --force to overwrite."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    result: Path | None = None
    with tempfile.TemporaryDirectory(prefix="corpora-cli-") as tmp:
        try:
            # text-fabric/cfabric print progress chatter straight to stdout;
            # route it to stderr so the only stdout line is the result path
            # (the scripting contract: `corpus=$(corpora convert ...)`).
            with contextlib.redirect_stdout(sys.stderr):
                result = run_conversion(
                    source_path=source,
                    work_dir=Path(tmp) / "work",
                    source_format=source_format,
                    output_path_for=output_path_for,
                    name=args.name or "",
                    description=args.description or "",
                    category=category,
                    on_log=_log,
                    on_display_name=lambda display: _log(f"Title: {display}"),
                    on_validation=_print_validation,
                )
        except CorpusValidationError as exc:
            # The archive was already written before the gate ran — keep it
            # (the user may want to inspect it) but fail the command.
            _log(f"error: {exc}")
            return 1
        except ConversionError as exc:
            _log(f"error: {exc}")
            return 1

    print(result)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    archive = Path(args.corpus).expanduser()
    if not archive.is_file():
        raise SystemExit(f"error: corpus file not found: {archive}")
    summary = validate_archive(archive)
    _print_validation(summary)
    return 0 if summary.get("valid") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corpora",
        description="Convert documents to .corpus archives locally, using "
        "the same pipeline as the corpora-api /convert endpoint.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser(
        "convert", help="Convert a source document into a .corpus archive."
    )
    convert.add_argument("source", help="Path to the source document.")
    convert.add_argument(
        "--format",
        "-f",
        choices=[fmt.value for fmt in SourceFormat],
        help="Source format (inferred from the file extension when omitted; "
        "required for .zip sources).",
    )
    convert.add_argument(
        "--name", "-n", help="Corpus name (fallback when the source has no title)."
    )
    convert.add_argument("--description", "-d", help="Corpus description.")
    convert.add_argument(
        "--category",
        "-c",
        choices=[cat.value for cat in CorpusCategory],
        help="Corpus structure category (auto-detected when omitted; an "
        "upgrade the document tree can't support is downgraded with a "
        "warning).",
    )
    convert.add_argument(
        "--output",
        "-o",
        help="Output .corpus path (default: ./<slugified-title>.corpus).",
    )
    convert.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    convert.set_defaults(func=_cmd_convert)

    validate = subparsers.add_parser(
        "validate", help="Run the corpus integrity checks over a .corpus file."
    )
    validate.add_argument("corpus", help="Path to a .corpus archive.")
    validate.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
