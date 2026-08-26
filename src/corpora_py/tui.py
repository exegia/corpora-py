"""``corpora`` terminal UI — a Textual app over the local pipeline surfaces.

Launched by bare ``corpora`` (or ``corpora ui``); the argparse subcommands in
`corpora_py.cli` remain the scripting interface. One tab per surface, each
mirroring an HTTP endpoint of `corpora-api` but calling the same underlying
functions in-process (no server):

- **Convert** — `POST /convert`: upload gate → parse → TF → ``.cfm`` →
  ``.corpus`` → validation gate, via `admin.services.conversion.run_conversion`.
- **Validate** — `POST /validate`: `validate_archive` over an existing file.
- **Library** — `/storage`: list / publish / download / delete stored
  archives via `make_corpus_storage()` (Hub or Supabase backend per
  settings; unconfigured storage degrades to a friendly message).
- **Library → open** — `/storage/{filename}/manifest|sections|content`: the
  corpus detail screen (manifest, section tree, passage reader) via
  `admin.services.corpus_detail`.

`/ingest` (Docling) is deliberately absent: it needs the heavy
``corpora-admin[docling]`` extra and has its own product surface.

Every pipeline/storage call runs in a Textual thread worker — they are
blocking CPU or network calls — and reports back through
``call_from_thread``. Text-fabric prints progress chatter straight to
stdout; workers route it to ``os.devnull`` for the duration of a call so it
never corrupts the terminal (the Textual driver holds its own handle to the
real tty).
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

from admin.parsers.schema import CorpusCategory, SourceFormat
from admin.services.conversion import (
    ConversionError,
    run_conversion,
    validate_archive,
)
from admin.services.storage import StorageError, StorageNotConfiguredError, make_corpus_storage
from admin.services.upload_validation import validate_upload
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

from .cli import _EXTENSION_FORMATS, _slugify

_AUTO = "auto"


def _summary_lines(summary: dict[str, Any]) -> list[str]:
    """Render a validation summary the same way the CLI does."""
    lines = [f"Validation: {'valid' if summary.get('valid') else 'INVALID'}"]
    stats = summary.get("stats") or {}
    if stats:
        lines.append("  stats: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    lines.extend(f"  reason: {r}" for r in summary.get("reasons") or [])
    return lines


@contextlib.contextmanager
def _muted_stdout():
    """Silence text-fabric/cfabric stdout chatter during a pipeline call."""
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
        yield


class ConvertPane(VerticalScroll):
    """The `POST /convert` surface: pick a source, run the full pipeline."""

    def compose(self) -> ComposeResult:
        yield Label("Source document")
        yield Input(placeholder="path/to/book.epub", id="convert-source")
        with HorizontalGroup():
            yield Select(
                [(f"format: {_AUTO}", _AUTO)]
                + [(f.value, f.value) for f in SourceFormat],
                value=_AUTO,
                allow_blank=False,
                id="convert-format",
            )
            yield Select(
                [(f"category: {_AUTO}", _AUTO)]
                + [(c.value, c.value) for c in CorpusCategory],
                value=_AUTO,
                allow_blank=False,
                id="convert-category",
            )
        yield Input(placeholder="name (fallback title)", id="convert-name")
        yield Input(placeholder="description", id="convert-description")
        yield Input(
            placeholder="output path (default: ./<slug>.corpus)",
            id="convert-output",
        )
        yield Button("Convert", variant="primary", id="convert-run")
        yield RichLog(id="convert-log", markup=False, wrap=True)

    def _log(self, message: str) -> None:
        self.query_one("#convert-log", RichLog).write(message)

    @on(Button.Pressed, "#convert-run")
    def start(self) -> None:
        source = Path(self.query_one("#convert-source", Input).value.strip()).expanduser()
        if not source.is_file():
            self._log(f"error: source file not found: {source}")
            return
        declared = self.query_one("#convert-format", Select).value
        if declared == _AUTO:
            if source.suffix.lower() == ".zip":
                self._log("error: a .zip source is ambiguous — pick tf_zip or tei_zip.")
                return
            fmt = _EXTENSION_FORMATS.get(source.suffix.lower())
            if fmt is None:
                self._log(f"error: cannot infer a format from '{source.name}' — pick one.")
                return
        else:
            fmt = SourceFormat(str(declared))
        category_value = self.query_one("#convert-category", Select).value
        category = None if category_value == _AUTO else CorpusCategory(str(category_value))
        raw_output = self.query_one("#convert-output", Input).value.strip()
        self.query_one("#convert-run", Button).disabled = True
        self.run_conversion_worker(
            source,
            fmt,
            category,
            self.query_one("#convert-name", Input).value.strip(),
            self.query_one("#convert-description", Input).value.strip(),
            Path(raw_output).expanduser() if raw_output else None,
        )

    @work(thread=True, exclusive=True, group="convert")
    def run_conversion_worker(
        self,
        source: Path,
        fmt: SourceFormat,
        category: CorpusCategory | None,
        name: str,
        description: str,
        output: Path | None,
    ) -> None:
        import tempfile

        app = self.app

        def log(message: str) -> None:
            app.call_from_thread(self._log, message)

        def log_summary(summary: dict[str, Any]) -> None:
            for line in _summary_lines(summary):
                log(line)

        def output_path_for(display_name: str) -> Path:
            path = output or Path.cwd() / (
                f"{_slugify(display_name) or _slugify(source.stem) or 'corpus'}.corpus"
            )
            if path.exists():
                raise ConversionError(f"{path} already exists — set an output path.")
            path.parent.mkdir(parents=True, exist_ok=True)
            return path

        try:
            report = validate_upload(source, fmt)
            for warning in report.warnings:
                log(f"warning: {warning}")
            if not report.convertible:
                for reason in report.reasons:
                    log(f"error: {reason}")
                return
            with tempfile.TemporaryDirectory(prefix="corpora-tui-") as tmp, _muted_stdout():
                result = run_conversion(
                    source_path=source,
                    work_dir=Path(tmp) / "work",
                    source_format=fmt,
                    output_path_for=output_path_for,
                    name=name,
                    description=description,
                    category=category,
                    on_log=log,
                    on_display_name=lambda display: log(f"Title: {display}"),
                    on_validation=log_summary,
                )
            log(f"Done: {result}")
        except ConversionError as exc:
            log(f"error: {exc}")
        except Exception as exc:  # a TUI must not die with the pipeline
            log(f"error: conversion failed: {exc!r}")
        finally:
            app.call_from_thread(
                setattr, self.query_one("#convert-run", Button), "disabled", False
            )


class ValidatePane(VerticalScroll):
    """The `POST /validate` surface: integrity checks over a `.corpus` file."""

    def compose(self) -> ComposeResult:
        yield Label("Corpus archive")
        yield Input(placeholder="path/to/book.corpus", id="validate-source")
        yield Button("Validate", variant="primary", id="validate-run")
        yield RichLog(id="validate-log", markup=False, wrap=True)

    def _log(self, message: str) -> None:
        self.query_one("#validate-log", RichLog).write(message)

    @on(Button.Pressed, "#validate-run")
    def start(self) -> None:
        archive = Path(self.query_one("#validate-source", Input).value.strip()).expanduser()
        if not archive.is_file():
            self._log(f"error: corpus file not found: {archive}")
            return
        self.query_one("#validate-run", Button).disabled = True
        self.run_validate_worker(archive)

    @work(thread=True, exclusive=True, group="validate")
    def run_validate_worker(self, archive: Path) -> None:
        app = self.app
        try:
            with _muted_stdout():
                summary = validate_archive(archive)
            for line in _summary_lines(summary):
                app.call_from_thread(self._log, line)
        except Exception as exc:
            app.call_from_thread(self._log, f"error: validation failed: {exc!r}")
        finally:
            app.call_from_thread(
                setattr, self.query_one("#validate-run", Button), "disabled", False
            )


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no confirmation for destructive Library actions."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._prompt)
            with Horizontal():
                yield Button("Cancel", id="confirm-no")
                yield Button("Delete", variant="error", id="confirm-yes")

    @on(Button.Pressed)
    def resolve(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")


class CorpusDetailScreen(Screen):
    """`/storage/{filename}/manifest|sections|content` as one read screen."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, filename: str) -> None:
        super().__init__()
        self.filename = filename

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="detail-left"):
                yield Static(f"[b]{self.filename}[/b]", id="detail-title")
                yield DataTable(id="detail-manifest", show_header=False)
                yield Tree("sections", id="detail-sections")
            yield RichLog(id="detail-content", markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#detail-manifest", DataTable)
        table.add_columns("key", "value")
        self.load_detail_worker()

    @work(thread=True, exclusive=True, group="detail")
    def load_detail_worker(self) -> None:
        from admin.services.corpus_detail import get_index, get_manifest

        app = self.app
        log = self.query_one("#detail-content", RichLog)
        try:
            with _muted_stdout():
                manifest = get_manifest(self.filename)
                index = get_index(self.filename)
        except Exception as exc:
            app.call_from_thread(log.write, f"error: could not load corpus: {exc!r}")
            return
        app.call_from_thread(self._render_detail, manifest, index)

    def _render_detail(self, manifest: dict[str, Any], index: dict[str, Any]) -> None:
        table = self.query_one("#detail-manifest", DataTable)
        for key, value in manifest.items():
            if isinstance(value, (str, int, float, bool)) and str(value):
                table.add_row(str(key), str(value))
        tree = self.query_one("#detail-sections", Tree)
        tree.root.expand()
        # `sections` is `{"levels": [...], "items": [...]}` (see
        # corpus_detail._build_sections); each item carries `title`/`ref` and
        # one level of `children`.
        sections = index.get("sections") or {}
        for item in sections.get("items") or []:
            node = tree.root.add(
                str(item.get("title") or item.get("ref")), data=item.get("ref")
            )
            for child in item.get("children") or []:
                node.add_leaf(
                    str(child.get("title") or child.get("ref")), data=child.get("ref")
                )
            if not item.get("children"):
                node.allow_expand = False

    @on(Tree.NodeSelected)
    def show_section(self, event: Tree.NodeSelected) -> None:
        if event.node.data is not None:
            self.load_content_worker(str(event.node.data))

    @work(thread=True, exclusive=True, group="detail-content")
    def load_content_worker(self, ref: str) -> None:
        from admin.services.corpus_detail import get_content

        app = self.app
        log = self.query_one("#detail-content", RichLog)
        try:
            with _muted_stdout():
                content = get_content(self.filename, ref=ref)
        except Exception as exc:
            app.call_from_thread(log.write, f"error: could not read '{ref}': {exc!r}")
            return

        def render() -> None:
            log.clear()
            log.write(f"— {ref} —")
            for passage in content.get("passages") or []:
                text = passage.get("text") if isinstance(passage, dict) else str(passage)
                if text:
                    log.write(text)
            total = content.get("total")
            shown = len(content.get("passages") or [])
            if total and total > shown:
                log.write(f"… {shown} of {total} passages shown")

        app.call_from_thread(render)


class LibraryPane(VerticalScroll):
    """The `/storage` surface: stored archives on the configured backend."""

    def compose(self) -> ComposeResult:
        with HorizontalGroup():
            yield Button("Refresh", id="library-refresh")
            yield Button("Open", id="library-open")
            yield Button("Download", id="library-download")
            yield Button("Delete", variant="error", id="library-delete")
        with HorizontalGroup():
            yield Input(placeholder="path/to/local.corpus to publish", id="library-publish-path")
            yield Button("Publish", variant="primary", id="library-publish")
        yield DataTable(id="library-table", cursor_type="row")
        yield RichLog(id="library-log", markup=False, wrap=True)

    def on_mount(self) -> None:
        table = self.query_one("#library-table", DataTable)
        table.add_columns("filename", "size", "repo")

    def _log(self, message: str) -> None:
        self.query_one("#library-log", RichLog).write(message)

    def _selected_filename(self) -> str | None:
        table = self.query_one("#library-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            self._log("error: no corpus selected — Refresh and pick a row first.")
            return None
        return str(table.get_row_at(table.cursor_row)[0])

    @on(Button.Pressed, "#library-refresh")
    def refresh_list(self) -> None:
        self.run_storage_worker("list")

    @on(Button.Pressed, "#library-open")
    def open_detail(self) -> None:
        filename = self._selected_filename()
        if filename:
            self.app.push_screen(CorpusDetailScreen(filename))

    @on(Button.Pressed, "#library-download")
    def download(self) -> None:
        filename = self._selected_filename()
        if filename:
            self.run_storage_worker("download", filename)

    @on(Button.Pressed, "#library-delete")
    def delete(self) -> None:
        filename = self._selected_filename()
        if not filename:
            return

        def confirmed(result: bool | None) -> None:
            if result:
                self.run_storage_worker("delete", filename)

        self.app.push_screen(ConfirmScreen(f"Delete {filename} from storage?"), confirmed)

    @on(Button.Pressed, "#library-publish")
    def publish(self) -> None:
        raw = self.query_one("#library-publish-path", Input).value.strip()
        path = Path(raw).expanduser()
        if not raw or not path.is_file():
            self._log(f"error: local corpus not found: {raw or '(empty)'}")
            return
        self.run_storage_worker("publish", str(path))

    @work(thread=True, group="library")
    def run_storage_worker(self, action: str, argument: str | None = None) -> None:
        app = self.app

        def log(message: str) -> None:
            app.call_from_thread(self._log, message)

        try:
            storage = make_corpus_storage()
            if action == "list":
                rows = [(c.filename, c.size_bytes, c.repo_id) for c in storage.list()]
                app.call_from_thread(self._render_rows, rows)
            elif action == "download":
                assert argument is not None
                dest = storage.download(argument, Path.cwd())
                log(f"Downloaded: {dest}")
            elif action == "delete":
                assert argument is not None
                storage.delete(argument)
                log(f"Deleted: {argument}")
                app.call_from_thread(self.refresh_list)
            elif action == "publish":
                assert argument is not None
                stored = storage.upload(Path(argument))
                log(f"Published: {stored.filename} -> {stored.url}")
                app.call_from_thread(self.refresh_list)
        except StorageNotConfiguredError as exc:
            log(f"storage not configured: {exc}")
        except StorageError as exc:
            log(f"storage error: {exc}")
        except Exception as exc:
            log(f"error: {exc!r}")

    def _render_rows(self, rows: list[tuple[str, int | None, str]]) -> None:
        table = self.query_one("#library-table", DataTable)
        table.clear()
        for filename, size_bytes, repo_id in rows:
            size = f"{size_bytes / (1024 * 1024):.1f} MB" if size_bytes else "?"
            table.add_row(filename, size, repo_id)
        self._log(f"{len(rows)} stored corpora.")


class CorporaApp(App):
    """Tabbed terminal UI over the local corpora surfaces."""

    TITLE = "corpora"
    BINDINGS = [("q", "quit", "Quit")]
    CSS = """
    ConvertPane, ValidatePane, LibraryPane { padding: 1 2; }
    Input, Select { margin-bottom: 1; }
    HorizontalGroup Button { margin-right: 1; }
    RichLog { height: 1fr; min-height: 8; border: round $surface-lighten-2; }
    #confirm-box {
        align: center middle; padding: 2 4; width: auto; height: auto;
        background: $panel; border: thick $error;
    }
    #confirm-box Button { margin: 1 2 0 0; }
    ConfirmScreen { align: center middle; }
    #detail-left { width: 45%; }
    #detail-manifest { height: auto; max-height: 40%; }
    #detail-sections { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent():
            with TabPane("Convert", id="tab-convert"):
                yield ConvertPane()
            with TabPane("Validate", id="tab-validate"):
                yield ValidatePane()
            with TabPane("Library", id="tab-library"):
                yield LibraryPane()
        yield Footer()


def run() -> int:
    """Entry point used by bare ``corpora`` / ``corpora ui``."""
    CorporaApp().run()
    return 0
