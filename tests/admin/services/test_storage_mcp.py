"""Tests for the `storage_*` MCP tools (`admin.services.storage_mcp`).

`register_storage_tools()` is called with a recorder standing in for the
FastMCP server, then the captured tool coroutines are invoked directly with
`corpus_storage` monkeypatched -- the tool surface (names, text output,
`ToolError` mapping) is what's under test, not FastMCP itself and not the
Hub wrapper (covered by `test_storage.py`).
"""

from pathlib import Path

import pytest
from admin.services import storage_mcp
from admin.services.storage import CorpusNotFoundError, StorageNotConfiguredError, StoredCorpus
from fastmcp.exceptions import ToolError


class RecordingMCP:
    """Captures functions registered via @mcp.tool()."""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class FakeStorage:
    def __init__(self, stored=None):
        self.stored = stored or []
        self.deleted = []

    def list(self):
        return self.stored

    def info(self, filename):
        for s in self.stored:
            if s.filename == filename:
                return s
        raise CorpusNotFoundError(f"No corpus named {filename!r}")

    def upload(self, path, filename=None):
        return _stored(filename or Path(path).name)

    def download(self, filename, dest_dir):
        self.info(filename)
        return Path(dest_dir) / filename

    def delete(self, filename):
        self.info(filename)
        self.deleted.append(filename)


def _stored(filename="BHSA.corpus") -> StoredCorpus:
    return StoredCorpus(
        filename=filename,
        size_bytes=10,
        repo_id="user/archives",
        url=f"https://huggingface.co/datasets/user/archives/resolve/main/{filename}",
    )


@pytest.fixture
def tools(monkeypatch):
    def _make(storage: FakeStorage):
        monkeypatch.setattr(storage_mcp, "corpus_storage", storage)
        mcp = RecordingMCP()
        storage_mcp.register_storage_tools(mcp)
        return mcp.tools

    return _make


def test_registers_all_five_tools(tools):
    registered = tools(FakeStorage())
    assert set(registered) == {
        "storage_list_corpora",
        "storage_corpus_info",
        "storage_upload_corpus",
        "storage_download_corpus",
        "storage_delete_corpus",
    }


async def test_list_empty(tools):
    registered = tools(FakeStorage())
    assert await registered["storage_list_corpora"]() == "No corpora in Hub storage."


async def test_list_describes_archives(tools):
    registered = tools(FakeStorage([_stored()]))
    out = await registered["storage_list_corpora"]()
    assert "BHSA.corpus (10 bytes)" in out
    assert "user/archives" in out


async def test_info_missing_raises_tool_error(tools):
    registered = tools(FakeStorage())
    with pytest.raises(ToolError, match="No corpus named"):
        await registered["storage_corpus_info"]("absent.corpus")


async def test_upload_reports_stored_archive(tools, tmp_path):
    registered = tools(FakeStorage())
    out = await registered["storage_upload_corpus"](str(tmp_path / "mini.corpus"))
    assert out.startswith("Uploaded:")
    assert "mini.corpus" in out


async def test_download_reports_local_path(tools, tmp_path):
    registered = tools(FakeStorage([_stored()]))
    out = await registered["storage_download_corpus"]("BHSA.corpus", str(tmp_path))
    assert str(tmp_path / "BHSA.corpus") in out


async def test_delete(tools):
    storage = FakeStorage([_stored()])
    registered = tools(storage)
    out = await registered["storage_delete_corpus"]("BHSA.corpus")
    assert "Deleted BHSA.corpus" in out
    assert storage.deleted == ["BHSA.corpus"]


async def test_not_configured_surfaces_as_tool_error(tools):
    storage = FakeStorage()

    def boom():
        raise StorageNotConfiguredError("set HF_STORAGE_REPO")

    storage.list = boom
    registered = tools(storage)
    with pytest.raises(ToolError, match="HF_STORAGE_REPO"):
        await registered["storage_list_corpora"]()


# ── read-only mode (HF_READ_ONLY) ─────────────────────────────────────────────
# A public read-only deployment must not even expose the write tools, so a
# client never sees a tool it could call to mutate the Hub.

_WRITE_TOOLS = {
    "storage_upload_corpus",
    "storage_delete_corpus",
    "corpus_manifest_update",
    "corpus_node_annotate",
}


def _register(read_only: bool) -> set[str]:
    from admin.services import corpus_detail_mcp

    rec = RecordingMCP()
    storage_mcp.register_storage_tools(rec, read_only=read_only)
    corpus_detail_mcp.register_corpus_detail_tools(rec, read_only=read_only)
    return set(rec.tools)


def test_read_only_omits_write_tools():
    names = _register(read_only=True)
    assert names.isdisjoint(_WRITE_TOOLS)
    # Reads stay registered.
    assert {"storage_list_corpora", "storage_download_corpus", "corpus_content"} <= names


def test_writable_registers_write_tools():
    assert _WRITE_TOOLS <= _register(read_only=False)
