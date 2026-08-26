"""Tests for the ``corpora`` terminal UI (`corpora_py.tui`).

Driven headlessly through Textual's pilot (`App.run_test`, pytest-asyncio in
auto mode). The pipeline/storage calls are monkeypatched at the `tui` module
seams — the real pipeline is covered by `test_cli.py` and the services
suites; here the contract under test is the wiring: inputs → worker →
log/table output, and the graceful degradation paths (missing file,
unconfigured storage).
"""

from pathlib import Path

from textual.widgets import Button, DataTable, Input, RichLog, Tree

from corpora_py import tui
from corpora_py.tui import CorporaApp, CorpusDetailScreen


def _log_text(app, selector: str) -> str:
    log = app.screen.query_one(selector, RichLog)
    # RichLog stores rendered Strips; `Strip.text` is the plain string.
    return "\n".join(strip.text for strip in log.lines)


async def _settle(app, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


async def _show_tab(app, pilot, tab_id: str) -> None:
    # A RichLog inside a hidden TabPane has no size and defers its writes,
    # so tests must surface the pane the way a user would.
    from textual.widgets import TabbedContent

    app.query_one(TabbedContent).active = tab_id
    await pilot.pause()


class TestConvertPane:
    async def test_missing_source_logs_error_without_worker(self):
        app = CorporaApp()
        async with app.run_test() as pilot:
            app.query_one("#convert-source", Input).value = "/nope/missing.txt"
            app.query_one("#convert-run", Button).press()
            await pilot.pause()
            await _settle(app, pilot)
            assert "source file not found" in _log_text(app, "#convert-log")
            assert not app.query_one("#convert-run", Button).disabled

    async def test_convert_runs_pipeline_and_logs_result(self, tmp_path, monkeypatch):
        source = tmp_path / "book.txt"
        source.write_text("Title\n\nHello world paragraph.\n")
        output = tmp_path / "book.corpus"

        def fake_run_conversion(**kwargs):
            kwargs["on_display_name"]("Fake Title")
            kwargs["on_log"]("Converting...")
            kwargs["on_validation"]({"valid": True, "stats": {"max_slot": 3}, "reasons": []})
            path = kwargs["output_path_for"]("Fake Title")
            path.write_bytes(b"archive")
            return path

        monkeypatch.setattr(tui, "run_conversion", fake_run_conversion)

        app = CorporaApp()
        async with app.run_test() as pilot:
            app.query_one("#convert-source", Input).value = str(source)
            app.query_one("#convert-output", Input).value = str(output)
            app.query_one("#convert-run", Button).press()
            await pilot.pause()
            await _settle(app, pilot)

            text = _log_text(app, "#convert-log")
            assert "Title: Fake Title" in text
            assert "Validation: valid" in text
            # The log soft-wraps long paths, so compare wrap-insensitively.
            assert f"Done: {output}" in text.replace("\n", "")
            assert output.read_bytes() == b"archive"
            assert not app.query_one("#convert-run", Button).disabled

    async def test_conversion_error_is_logged_not_raised(self, tmp_path, monkeypatch):
        source = tmp_path / "book.txt"
        source.write_text("content")

        def failing_run_conversion(**kwargs):
            raise tui.ConversionError("not a valid source")

        monkeypatch.setattr(tui, "run_conversion", failing_run_conversion)

        app = CorporaApp()
        async with app.run_test() as pilot:
            app.query_one("#convert-source", Input).value = str(source)
            app.query_one("#convert-run", Button).press()
            await pilot.pause()
            await _settle(app, pilot)
            assert "error: not a valid source" in _log_text(app, "#convert-log")

    async def test_zip_needs_explicit_format(self, tmp_path):
        source = tmp_path / "dataset.zip"
        source.write_bytes(b"PK\x03\x04")

        app = CorporaApp()
        async with app.run_test() as pilot:
            app.query_one("#convert-source", Input).value = str(source)
            app.query_one("#convert-run", Button).press()
            await pilot.pause()
            await _settle(app, pilot)
            assert "ambiguous" in _log_text(app, "#convert-log")


class TestValidatePane:
    async def test_validates_and_prints_summary(self, tmp_path, monkeypatch):
        archive = tmp_path / "book.corpus"
        archive.write_bytes(b"zip")
        monkeypatch.setattr(
            tui,
            "validate_archive",
            lambda path: {"valid": False, "stats": {}, "reasons": ["broken otype"]},
        )

        app = CorporaApp()
        async with app.run_test() as pilot:
            await _show_tab(app, pilot, "tab-validate")
            app.query_one("#validate-source", Input).value = str(archive)
            app.query_one("#validate-run", Button).press()
            await pilot.pause()
            await _settle(app, pilot)
            text = _log_text(app, "#validate-log")
            assert "Validation: INVALID" in text
            assert "broken otype" in text


class _FakeStored:
    def __init__(self, filename):
        self.filename = filename
        self.size_bytes = 2 * 1024 * 1024
        self.repo_id = "user/archives"
        self.url = f"https://hub/{filename}"


class _FakeStorage:
    def __init__(self):
        self.deleted: list[str] = []

    def list(self):
        return [_FakeStored("alpha.corpus"), _FakeStored("beta.corpus")]

    def download(self, filename, dest_dir):
        return Path(dest_dir) / filename

    def delete(self, filename):
        self.deleted.append(filename)

    def upload(self, local_path, filename=None):
        return _FakeStored(Path(local_path).name)


class TestLibraryPane:
    async def test_refresh_populates_table(self, monkeypatch):
        monkeypatch.setattr(tui, "make_corpus_storage", lambda: _FakeStorage())

        app = CorporaApp()
        async with app.run_test() as pilot:
            await _show_tab(app, pilot, "tab-library")
            app.query_one("#library-table", DataTable)  # pane composes
            app.query_one("#library-refresh", Button).press()
            await pilot.pause()
            await _settle(app, pilot)
            table = app.query_one("#library-table", DataTable)
            assert table.row_count == 2
            assert "2 stored corpora." in _log_text(app, "#library-log")

    async def test_unconfigured_storage_degrades_to_message(self, monkeypatch):
        def raising():
            raise tui.StorageNotConfiguredError("set HF_STORAGE_REPO")

        monkeypatch.setattr(tui, "make_corpus_storage", raising)

        app = CorporaApp()
        async with app.run_test() as pilot:
            await _show_tab(app, pilot, "tab-library")
            app.query_one("#library-refresh", Button).press()
            await pilot.pause()
            await _settle(app, pilot)
            assert "storage not configured" in _log_text(app, "#library-log")

    async def test_publish_requires_existing_file(self):
        app = CorporaApp()
        async with app.run_test() as pilot:
            await _show_tab(app, pilot, "tab-library")
            app.query_one("#library-publish-path", Input).value = "/nope.corpus"
            app.query_one("#library-publish", Button).press()
            await pilot.pause()
            await _settle(app, pilot)
            assert "local corpus not found" in _log_text(app, "#library-log")


class TestCorpusDetailScreen:
    async def test_renders_manifest_and_sections(self, monkeypatch):
        import admin.services.corpus_detail as detail

        monkeypatch.setattr(
            detail, "get_manifest", lambda filename: {"name": "Alpha", "category": "book"}
        )
        monkeypatch.setattr(
            detail,
            "get_index",
            lambda filename: {
                "toc": None,
                "sections": {
                    "levels": ["book", "chapter"],
                    "items": [
                        {
                            "title": "Alpha",
                            "ref": "Alpha",
                            "children": [{"title": "Chapter 1", "ref": "Alpha 1"}],
                        }
                    ],
                },
                "node_types": [],
            },
        )
        monkeypatch.setattr(
            detail,
            "get_content",
            lambda filename, ref=None, **kw: {
                "ref": ref,
                "passages": [{"text": "In the beginning"}],
                "total": 1,
            },
        )

        app = CorporaApp()
        async with app.run_test() as pilot:
            app.push_screen(CorpusDetailScreen("alpha.corpus"))
            await _settle(app, pilot)

            table = app.screen.query_one("#detail-manifest", DataTable)
            assert table.row_count == 2
            tree = app.screen.query_one("#detail-sections", Tree)
            assert len(tree.root.children) == 1

            tree.select_node(tree.root.children[0])
            await _settle(app, pilot)
            assert "In the beginning" in _log_text(app, "#detail-content")


class TestCliWiring:
    def test_bare_invocation_routes_to_ui(self, monkeypatch):
        from corpora_py import cli

        calls = []
        monkeypatch.setattr(
            "corpora_py.tui.run", lambda: calls.append("ran") or 0
        )
        assert cli.main([]) == 0
        assert calls == ["ran"]
