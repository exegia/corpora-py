"""``corpora`` — terminal CLI over the conversion pipeline (issue #188).

Runs the exact same pipeline as ``POST /convert`` — upload gate →
parse → Text-Fabric → ``.cfm`` → ``.corpus`` → validation gate — but
locally and synchronously, with no server, jobs, or transport involved:
everything goes through the transport-free
`admin.services.conversion.run_conversion` seam. This is the
super-admin's local conversion path (see issues #185/#187/#188 — the
hosted poll-driven transport is being retired in favor of local
conversion).

Output goes through Rich (colour, tables, a spinner on a live tty) but
stays line-oriented and scriptable — plain argparse subcommands, no
interactive screens. The former Textual TUI (`corpora ui`) is gone; its
Library surface lives on as the ``corpora library`` subcommands below.

Usage::

    corpora convert mobydick.epub --name "Moby Dick" -o mobydick.corpus
    corpora convert dataset.zip --format tf_zip
    corpora validate mobydick.corpus
    corpora library list
    corpora library publish mobydick.corpus
    corpora library show mobydick.corpus --ref "Moby Dick 1"

Exit codes: 0 success; 1 conversion/validation/storage failure; 2 bad
usage (unreadable source, unknown format, upload gate rejection,
refusing to overwrite, unconfigured storage).

Scripting contract: the only stdout of ``convert`` is the result path
(``corpus=$(corpora convert ...)``); logs and decoration go to stderr.
``library list``/``show`` print their tables to stdout — they *are* the
command's output — and degrade to plain text when piped (Rich drops
colour on a non-tty; ``NO_COLOR`` is honoured).
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from admin.parsers.schema import CorpusCategory, SourceFormat
from admin.services.conversion import (
    ConversionError,
    CorpusValidationError,
    run_conversion,
    validate_archive,
)
from admin.services.upload_validation import validate_upload
from rich.console import Console

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

# stderr=True resolves sys.stderr per print, so pytest's capsys still
# captures; highlight=False keeps Rich from colouring numbers inside log
# lines, soft_wrap keeps paths greppable on one line.
_err = Console(stderr=True, highlight=False, soft_wrap=True)
_out = Console(highlight=False, soft_wrap=True)


def _log(message: str, style: str | None = None) -> None:
    _err.print(message, style=style, markup=False)


def _warn(message: str) -> None:
    _log(f"warning: {message}", style="yellow")


def _error(message: str) -> None:
    _log(f"error: {message}", style="bold red")


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
    if summary.get("valid"):
        _err.print("Validation: [green]valid[/green]")
    else:
        _err.print("Validation: [bold red]INVALID[/bold red]")
    stats = summary.get("stats") or {}
    if stats:
        rendered = ", ".join(f"{key}={value}" for key, value in stats.items())
        _log(f"  stats: {rendered}", style="dim")
    for reason in summary.get("reasons") or []:
        _log(f"  reason: {reason}", style="red")


def _cmd_convert(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    if not source.is_file():
        raise SystemExit(f"error: source file not found: {source}")
    source_format = _infer_format(source, args.format)

    # The same pre-conversion gate as POST /convert (issue #173): reject
    # obviously non-convertible bytes before spending minutes converting.
    report = validate_upload(source, source_format)
    for warning in report.warnings:
        _warn(warning)
    if not report.convertible:
        for reason in report.reasons:
            _error(reason)
        raise SystemExit(2)

    category = CorpusCategory(args.category) if args.category else None

    def output_path_for(display_name: str) -> Path:
        if args.output:
            path = Path(args.output).expanduser()
        else:
            stem = _slugify(display_name) or _slugify(source.stem) or "corpus"
            path = Path.cwd() / f"{stem}.corpus"
        if path.exists() and not args.force:
            raise SystemExit(f"error: {path} already exists — pass --force to overwrite.")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # A spinner on a live terminal only; piped/CI output stays plain lines.
    # Rich prints log lines above the spinner, so on_log stays untouched.
    status_cm = (
        _err.status(f"Converting {source.name}…") if _err.is_terminal else contextlib.nullcontext()
    )

    result: Path | None = None
    with tempfile.TemporaryDirectory(prefix="corpora-cli-") as tmp:
        try:
            # text-fabric/cfabric print progress chatter straight to stdout;
            # route it to stderr so the only stdout line is the result path
            # (the scripting contract: `corpus=$(corpora convert ...)`).
            with status_cm, contextlib.redirect_stdout(sys.stderr):
                result = run_conversion(
                    source_path=source,
                    work_dir=Path(tmp) / "work",
                    source_format=source_format,
                    output_path_for=output_path_for,
                    name=args.name or "",
                    description=args.description or "",
                    category=category,
                    on_log=_log,
                    on_display_name=lambda display: _log(f"Title: {display}", style="bold cyan"),
                    on_validation=_print_validation,
                )
        except CorpusValidationError as exc:
            # The archive was already written before the gate ran — keep it
            # (the user may want to inspect it) but fail the command.
            _error(str(exc))
            return 1
        except ConversionError as exc:
            _error(str(exc))
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


# ── library ──────────────────────────────────────────────────────────────────
# The `/storage` and `/storage/{filename}/…` surfaces of corpora-api as
# plain subcommands (they were the Library tab of the retired Textual TUI),
# calling the same in-process services. Storage imports are lazy: the
# scripting subcommands must not pay for the storage backends.


def _storage():
    from admin.services.storage import make_corpus_storage

    return make_corpus_storage()


def _run_library(args: argparse.Namespace) -> int:
    from admin.services.storage import StorageError, StorageNotConfiguredError

    try:
        return args.library_func(args)
    except StorageNotConfiguredError as exc:
        raise SystemExit(f"error: storage not configured: {exc}") from exc
    except StorageError as exc:
        _error(f"storage error: {exc}")
        return 1


def _cmd_library_list(_args: argparse.Namespace) -> int:
    from rich.table import Table

    corpora = list(_storage().list())
    table = Table(box=None, pad_edge=False, header_style="bold")
    table.add_column("filename", style="cyan", overflow="fold")
    table.add_column("size", justify="right")
    table.add_column("repo", style="dim", overflow="fold")
    for item in corpora:
        size = f"{item.size_bytes / (1024 * 1024):.1f} MB" if item.size_bytes else "?"
        table.add_row(item.filename, size, item.repo_id)
    _out.print(table)
    _log(f"{len(corpora)} stored corpora.", style="dim")
    return 0


def _cmd_library_publish(args: argparse.Namespace) -> int:
    path = Path(args.corpus).expanduser()
    if not path.is_file():
        raise SystemExit(f"error: local corpus not found: {path}")
    stored = _storage().upload(path)
    _log(f"Published: {stored.filename}", style="green")
    print(stored.url)
    return 0


def _cmd_library_download(args: argparse.Namespace) -> int:
    dest_dir = Path(args.dest).expanduser() if args.dest else Path.cwd()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _storage().download(args.filename, dest_dir)
    print(dest)
    return 0


def _cmd_library_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit(
                f"error: refusing to delete {args.filename} without --yes "
                "(stdin is not a terminal)."
            )
        from rich.prompt import Confirm

        if not Confirm.ask(f"Delete [cyan]{args.filename}[/cyan] from storage?", console=_err):
            _log("Aborted.", style="dim")
            return 1
    _storage().delete(args.filename)
    _log(f"Deleted: {args.filename}", style="green")
    return 0


def _cmd_library_show(args: argparse.Namespace) -> int:
    from admin.services.corpus_detail import get_content, get_index, get_manifest
    from rich.table import Table
    from rich.tree import Tree

    # corpus_detail (via text-fabric) chatters on stdout; keep stdout clean
    # for the rendered output.
    with contextlib.redirect_stdout(sys.stderr):
        manifest = get_manifest(args.filename)
        index = get_index(args.filename)
        content = get_content(args.filename, ref=args.ref) if args.ref else None

    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    for key, value in manifest.items():
        if isinstance(value, (str, int, float, bool)) and str(value):
            table.add_row(str(key), str(value))
    _out.print(table)

    # `sections` is `{"levels": [...], "items": [...]}` (see
    # corpus_detail._build_sections); each item carries `title`/`ref` and
    # one level of `children`.
    sections: dict[str, Any] = index.get("sections") or {}
    tree = Tree("[bold]sections[/bold]")
    for item in sections.get("items") or []:
        node = tree.add(str(item.get("title") or item.get("ref")))
        for child in item.get("children") or []:
            node.add(str(child.get("title") or child.get("ref")))
    _out.print(tree)

    if content is not None:
        _out.print(f"\n[bold]— {args.ref} —[/bold]")
        for passage in content.get("passages") or []:
            text = passage.get("text") if isinstance(passage, dict) else str(passage)
            if text:
                _out.print(text, markup=False)
        total = content.get("total")
        shown = len(content.get("passages") or [])
        if total and total > shown:
            _log(f"… {shown} of {total} passages shown", style="dim")
    return 0


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

    library = subparsers.add_parser(
        "library", help="Manage stored archives on the configured backend."
    )
    library_sub = library.add_subparsers(dest="library_command", required=True)

    lib_list = library_sub.add_parser("list", help="List stored archives.")
    lib_list.set_defaults(func=_run_library, library_func=_cmd_library_list)

    lib_publish = library_sub.add_parser(
        "publish", help="Upload a local .corpus archive to storage."
    )
    lib_publish.add_argument("corpus", help="Path to a local .corpus archive.")
    lib_publish.set_defaults(func=_run_library, library_func=_cmd_library_publish)

    lib_download = library_sub.add_parser("download", help="Download a stored archive.")
    lib_download.add_argument("filename", help="Stored archive filename.")
    lib_download.add_argument("--dest", help="Destination directory (default: current directory).")
    lib_download.set_defaults(func=_run_library, library_func=_cmd_library_download)

    lib_delete = library_sub.add_parser("delete", help="Delete a stored archive.")
    lib_delete.add_argument("filename", help="Stored archive filename.")
    lib_delete.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt (required when not a terminal).",
    )
    lib_delete.set_defaults(func=_run_library, library_func=_cmd_library_delete)

    lib_show = library_sub.add_parser(
        "show", help="Show a stored archive's manifest and section tree."
    )
    lib_show.add_argument("filename", help="Stored archive filename.")
    lib_show.add_argument("--ref", help="Section reference whose passages should be printed.")
    lib_show.set_defaults(func=_run_library, library_func=_cmd_library_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    resolved = list(sys.argv[1:] if argv is None else argv)
    # Bare `corpora` prints the overview instead of argparse's terse usage
    # error (the Textual TUI it used to launch is gone).
    if not resolved:
        build_parser().print_help(sys.stderr)
        return 2
    args = build_parser().parse_args(resolved)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
