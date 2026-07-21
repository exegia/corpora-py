"""Tests for `admin.services.storage` (`CorpusStorage` over a fake `HfApi`).

Every test injects a `FakeHfApi` -- no network, no token. What's under test
is the wrapper's contract: filename sanitization, `.corpus` filtering, error
mapping (Hub 404s -> `CorpusNotFoundError`, missing config ->
`StorageNotConfiguredError`), and repo auto-creation on upload.
"""

from types import SimpleNamespace

import httpx
import pytest
from admin.services.storage import (
    CorpusNotFoundError,
    CorpusStorage,
    ReadOnlyStorageError,
    StorageError,
    StorageNotConfiguredError,
    _safe_archive_name,
)
from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError


def _entry(path: str, size: int = 100) -> SimpleNamespace:
    return SimpleNamespace(path=path, size=size)


def _hub_error(cls, message: str = "err", status: int = 404):
    """Hub v1 HTTP errors require a real httpx.Response at construction time.

    (`EntryNotFoundError` is a plain Exception in v1 and doesn't need this.)
    """
    response = httpx.Response(status, request=httpx.Request("GET", "https://huggingface.co"))
    return cls(message, response=response)


class FakeHfApi:
    """Records calls; canned per-method behavior set by each test."""

    def __init__(self, tree=None, paths_info=None):
        self.tree = tree or []
        self.paths_info = paths_info if paths_info is not None else []
        self.calls: list[tuple] = []

    def list_repo_tree(self, repo_id, repo_type=None, recursive=False):
        self.calls.append(("list_repo_tree", repo_id))
        if isinstance(self.tree, Exception):
            raise self.tree
        return iter(self.tree)

    def get_paths_info(self, repo_id, paths, repo_type=None):
        self.calls.append(("get_paths_info", repo_id, tuple(paths)))
        if isinstance(self.paths_info, Exception):
            raise self.paths_info
        return [e for e in self.paths_info if e.path in paths]

    def create_repo(self, repo_id, repo_type=None, private=None, exist_ok=False):
        self.calls.append(("create_repo", repo_id, private, exist_ok))

    def upload_file(self, *, path_or_fileobj, path_in_repo, repo_id, repo_type, commit_message):
        self.calls.append(("upload_file", path_or_fileobj, path_in_repo, repo_id))
        self.paths_info = [_entry(path_in_repo, size=7)]

    def hf_hub_download(self, repo_id, filename, repo_type=None, local_dir=None):
        self.calls.append(("hf_hub_download", repo_id, filename, local_dir))
        if not any(e.path == filename for e in self.paths_info):
            raise EntryNotFoundError(f"no {filename}")
        return f"{local_dir}/{filename}"

    def delete_file(self, path_in_repo, repo_id, repo_type=None, commit_message=None):
        self.calls.append(("delete_file", path_in_repo, repo_id))
        if not any(e.path == path_in_repo for e in self.paths_info):
            raise EntryNotFoundError(f"no {path_in_repo}")


@pytest.fixture
def api() -> FakeHfApi:
    return FakeHfApi()


@pytest.fixture
def storage(api) -> CorpusStorage:
    return CorpusStorage(repo_id="user/archives", repo_type="dataset", api=api)


# ── filename sanitization ─────────────────────────────────────────────────────


def test_safe_archive_name_appends_suffix_and_strips_paths():
    assert _safe_archive_name("BHSA") == "BHSA.corpus"
    assert _safe_archive_name("BHSA.corpus") == "BHSA.corpus"
    assert _safe_archive_name("../../etc/passwd") == "passwd.corpus"
    assert _safe_archive_name("nested/dir/x.corpus") == "x.corpus"


@pytest.mark.parametrize("bad", ["", ".", ".."])
def test_safe_archive_name_rejects_degenerate_names(bad):
    with pytest.raises(StorageError):
        _safe_archive_name(bad)


# ── configuration ─────────────────────────────────────────────────────────────


def test_unconfigured_repo_raises_not_configured(api):
    storage = CorpusStorage(repo_id="", api=api)
    with pytest.raises(StorageNotConfiguredError):
        storage.list()
    with pytest.raises(StorageNotConfiguredError):
        storage.info("x")
    with pytest.raises(StorageNotConfiguredError):
        storage.delete("x")


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_filters_to_corpus_archives(storage, api):
    api.tree = [_entry("BHSA.corpus", 10), _entry("README.md", 1), _entry("GNT.corpus", 20)]
    stored = storage.list()
    assert [s.filename for s in stored] == ["BHSA.corpus", "GNT.corpus"]
    assert stored[0].size_bytes == 10
    assert stored[0].repo_id == "user/archives"
    assert stored[0].url.endswith("/datasets/user/archives/resolve/main/BHSA.corpus")


def test_list_missing_repo_is_empty_library(storage, api):
    api.tree = _hub_error(RepositoryNotFoundError, "nope")
    assert storage.list() == []


# ── info ──────────────────────────────────────────────────────────────────────


def test_info_found(storage, api):
    api.paths_info = [_entry("BHSA.corpus", 42)]
    stored = storage.info("BHSA")  # suffix appended
    assert stored.filename == "BHSA.corpus"
    assert stored.size_bytes == 42


def test_info_missing_raises_not_found(storage, api):
    api.paths_info = []
    with pytest.raises(CorpusNotFoundError):
        storage.info("missing.corpus")


# ── upload ────────────────────────────────────────────────────────────────────


def test_upload_creates_repo_and_returns_info(storage, api, tmp_path):
    archive = tmp_path / "mini.corpus"
    archive.write_bytes(b"zip")
    stored = storage.upload(archive)
    assert stored.filename == "mini.corpus"
    assert ("create_repo", "user/archives", True, True) in api.calls
    assert any(c[0] == "upload_file" and c[2] == "mini.corpus" for c in api.calls)


def test_upload_honors_filename_override(storage, api, tmp_path):
    archive = tmp_path / "job-abc123.corpus"
    archive.write_bytes(b"zip")
    stored = storage.upload(archive, filename="My Book")
    assert stored.filename == "My Book.corpus"


def test_upload_missing_file_raises(storage, tmp_path):
    with pytest.raises(StorageError):
        storage.upload(tmp_path / "absent.corpus")


# ── download / delete ─────────────────────────────────────────────────────────


def test_download_returns_local_path(storage, api, tmp_path):
    api.paths_info = [_entry("BHSA.corpus")]
    local = storage.download("BHSA.corpus", tmp_path)
    assert local.name == "BHSA.corpus"


def test_download_missing_raises_not_found(storage, api, tmp_path):
    with pytest.raises(CorpusNotFoundError):
        storage.download("missing.corpus", tmp_path)


def test_delete_missing_raises_not_found(storage, api):
    with pytest.raises(CorpusNotFoundError):
        storage.delete("missing.corpus")


def test_delete_existing(storage, api):
    api.paths_info = [_entry("BHSA.corpus")]
    storage.delete("BHSA.corpus")
    assert ("delete_file", "BHSA.corpus", "user/archives") in api.calls


# ── read-only mode (HF_READ_ONLY) ─────────────────────────────────────────────
# The authoritative chokepoint: every Hub write funnels through upload/delete,
# so refusing here blocks all write paths (HTTP, MCP, future) by construction.


def test_read_only_blocks_upload(storage, api, monkeypatch, tmp_path):
    monkeypatch.setattr("admin.services.storage.settings.hf_read_only", True)
    archive = tmp_path / "x.corpus"
    archive.write_bytes(b"zip")
    with pytest.raises(ReadOnlyStorageError):
        storage.upload(archive)
    # Refused before any Hub call (repo creation, upload) is attempted.
    assert api.calls == []


def test_read_only_blocks_delete(storage, api, monkeypatch):
    api.paths_info = [_entry("BHSA.corpus")]
    monkeypatch.setattr("admin.services.storage.settings.hf_read_only", True)
    with pytest.raises(ReadOnlyStorageError):
        storage.delete("BHSA.corpus")
    assert api.calls == []
