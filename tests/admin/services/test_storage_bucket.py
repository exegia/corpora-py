"""Tests for the Hugging Face **bucket** backend of `CorpusStorage`.

Companion to `test_storage.py` (which covers the classic-repo backend). Same
contract -- filename sanitization, `.corpus` filtering, error mapping, and
location auto-creation on upload -- but exercised against a `FakeBucketApi`
that records the bucket-specific `huggingface_hub` calls (`create_bucket`,
`batch_bucket_files`, `list_bucket_tree`, `get_bucket_paths_info`,
`download_bucket_files`) instead of the repo ones. What matters is that a
`CorpusStorage(repo_type="bucket")` publishes/reads a corpus to/from a bucket,
not a dataset, while presenting the identical `StoredCorpus` surface.
"""

from types import SimpleNamespace

import httpx
import pytest
from admin.services.storage import (
    CorpusNotFoundError,
    CorpusStorage,
    StorageError,
    StorageNotConfiguredError,
)
from huggingface_hub.errors import BucketNotFoundError, EntryNotFoundError


def _file(path: str, size: int = 100) -> SimpleNamespace:
    """A BucketFile-shaped entry (type="file", path, size)."""
    return SimpleNamespace(type="file", path=path, size=size)


def _folder(path: str) -> SimpleNamespace:
    """A BucketFolder-shaped entry (no size) -- must be filtered out of list()."""
    return SimpleNamespace(type="directory", path=path)


def _hub_error(cls, message: str = "err", status: int = 404):
    response = httpx.Response(status, request=httpx.Request("GET", "https://huggingface.co"))
    return cls(message, response=response)


class FakeBucketApi:
    """Records bucket calls; canned per-method behavior set by each test."""

    def __init__(self, tree=None, paths_info=None):
        self.tree = tree or []
        self.paths_info = paths_info if paths_info is not None else []
        self.calls: list[tuple] = []

    def create_bucket(self, bucket_id, private=None, exist_ok=False):
        self.calls.append(("create_bucket", bucket_id, private, exist_ok))

    def list_bucket_tree(self, bucket_id, prefix=None, recursive=False):
        self.calls.append(("list_bucket_tree", bucket_id))
        if isinstance(self.tree, Exception):
            raise self.tree
        return iter(self.tree)

    def get_bucket_paths_info(self, bucket_id, paths):
        self.calls.append(("get_bucket_paths_info", bucket_id, tuple(paths)))
        if isinstance(self.paths_info, Exception):
            raise self.paths_info
        return [e for e in self.paths_info if e.path in paths]

    def batch_bucket_files(self, bucket_id, *, add=None, copy=None, delete=None):
        self.calls.append(("batch_bucket_files", bucket_id, add, delete))
        if add:
            self.paths_info = [_file(name, size=7) for _local, name in add]

    def download_bucket_files(self, bucket_id, files, *, raise_on_missing_files=False):
        self.calls.append(("download_bucket_files", bucket_id, tuple(files)))
        for remote, _dest in files:
            if raise_on_missing_files and not any(
                e.path == remote for e in self.paths_info
            ):
                raise EntryNotFoundError(f"no {remote}")


@pytest.fixture
def api() -> FakeBucketApi:
    return FakeBucketApi()


@pytest.fixture
def storage(api) -> CorpusStorage:
    return CorpusStorage(repo_id="user/archives", repo_type="bucket", api=api)


# ── configuration ─────────────────────────────────────────────────────────────


def test_unconfigured_bucket_raises_not_configured(api):
    storage = CorpusStorage(repo_id="", repo_type="bucket", api=api)
    with pytest.raises(StorageNotConfiguredError):
        storage.list()
    with pytest.raises(StorageNotConfiguredError):
        storage.info("x")


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_filters_to_corpus_archives_and_skips_folders(storage, api):
    api.tree = [
        _file("BHSA.corpus", 10),
        _folder("nested"),
        _file("README.md", 1),
        _file("GNT.corpus", 20),
    ]
    stored = storage.list()
    assert [s.filename for s in stored] == ["BHSA.corpus", "GNT.corpus"]
    assert stored[0].size_bytes == 10
    assert stored[0].repo_id == "user/archives"
    # Bucket resolve URL: no dataset/ prefix, no /main/ branch segment.
    assert stored[0].url == (
        "https://huggingface.co/buckets/user/archives/resolve/BHSA.corpus"
    )
    assert ("list_bucket_tree", "user/archives") in api.calls


def test_list_missing_bucket_is_empty_library(storage, api):
    api.tree = _hub_error(BucketNotFoundError, "nope")
    assert storage.list() == []


# ── info ──────────────────────────────────────────────────────────────────────


def test_info_found(storage, api):
    api.paths_info = [_file("BHSA.corpus", 42)]
    stored = storage.info("BHSA")  # suffix appended
    assert stored.filename == "BHSA.corpus"
    assert stored.size_bytes == 42
    assert ("get_bucket_paths_info", "user/archives", ("BHSA.corpus",)) in api.calls


def test_info_missing_raises_not_found(storage, api):
    api.paths_info = []
    with pytest.raises(CorpusNotFoundError):
        storage.info("missing.corpus")


# ── upload ────────────────────────────────────────────────────────────────────


def test_upload_creates_bucket_and_returns_info(storage, api, tmp_path):
    archive = tmp_path / "mini.corpus"
    archive.write_bytes(b"zip")
    stored = storage.upload(archive)
    assert stored.filename == "mini.corpus"
    assert ("create_bucket", "user/archives", True, True) in api.calls
    assert any(
        c[0] == "batch_bucket_files" and c[2] == [(str(archive), "mini.corpus")]
        for c in api.calls
    )


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
    api.paths_info = [_file("BHSA.corpus")]
    local = storage.download("BHSA.corpus", tmp_path)
    assert local == tmp_path / "BHSA.corpus"


def test_download_missing_raises_not_found(storage, api, tmp_path):
    with pytest.raises(CorpusNotFoundError):
        storage.download("missing.corpus", tmp_path)


def test_delete_missing_raises_not_found(storage, api):
    with pytest.raises(CorpusNotFoundError):
        storage.delete("missing.corpus")


def test_delete_existing(storage, api):
    api.paths_info = [_file("BHSA.corpus")]
    storage.delete("BHSA.corpus")
    assert ("batch_bucket_files", "user/archives", None, ["BHSA.corpus"]) in api.calls
