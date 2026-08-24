"""Tests for `admin.services.storage_supabase` (`SupabaseCorpusStorage`).

Every test injects a `FakeSession` -- no network, no key leaves the process.
Under test: the backend contract shared with `CorpusStorage` (filename
sanitization, `.corpus` filtering, error mapping, read-only refusal,
missing-config refusal), plus what's unique here: owner-prefixed object paths
driven by the `current_owner` ContextVar, and `make_corpus_storage`'s backend
selection.
"""

import json
from types import SimpleNamespace

import pytest
from admin.services import corpus_detail
from admin.services.storage import (
    CorpusNotFoundError,
    CorpusStorage,
    ReadOnlyStorageError,
    StorageError,
    StorageNotConfiguredError,
    make_corpus_storage,
)
from admin.services.storage_supabase import SupabaseCorpusStorage
from common.utils.config import settings
from common.utils.request_context import current_owner

BUCKET = "corpora"
URL = "https://proj.supabase.co"
KEY = "service-role-key"


def _resp(status: int = 200, body=None, text: str = "") -> SimpleNamespace:
    payload = body if body is not None else []
    return SimpleNamespace(
        status_code=status,
        text=text or (json.dumps(payload) if body is not None else ""),
        content=b"corpus-bytes",
        json=lambda: payload,
    )


def _object(name: str, size: int = 100, with_id: bool = True) -> dict:
    return {
        "name": name,
        "id": "obj-id" if with_id else None,
        "metadata": {"size": size},
    }


class FakeSession:
    """Records calls; canned per-(method, url-suffix) responses set by tests."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.responses: dict[str, SimpleNamespace] = {}
        self.default = _resp(200)

    def _dispatch(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for suffix, resp in self.responses.items():
            if url.endswith(suffix):
                return resp
        return self.default

    def post(self, url, **kwargs):
        return self._dispatch("post", url, **kwargs)

    def get(self, url, **kwargs):
        return self._dispatch("get", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._dispatch("delete", url, **kwargs)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def storage(session) -> SupabaseCorpusStorage:
    return SupabaseCorpusStorage(bucket=BUCKET, url=URL, key=KEY, session=session)


@pytest.fixture
def owner():
    token = current_owner.set("user-123")
    yield "user-123"
    current_owner.reset(token)


# ── configuration ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing", ["bucket", "url", "key"])
def test_unconfigured_raises_not_configured(session, missing):
    kwargs = {"bucket": BUCKET, "url": URL, "key": KEY, "session": session}
    kwargs[missing] = ""
    storage = SupabaseCorpusStorage(**kwargs)
    with pytest.raises(StorageNotConfiguredError):
        storage.list()
    with pytest.raises(StorageNotConfiguredError):
        storage.upload(__file__)
    assert session.calls == []


def test_url_trailing_slash_stripped(session):
    storage = SupabaseCorpusStorage(bucket=BUCKET, url=URL + "/", key=KEY, session=session)
    assert storage.url == URL


# ── list / info ────────────────────────────────────────────────────────────────


def test_list_anonymous_uses_empty_prefix(storage, session):
    session.default = _resp(200, [_object("a.corpus")])
    stored = storage.list()
    method, url, kwargs = session.calls[0]
    assert url == f"{URL}/storage/v1/object/list/{BUCKET}"
    assert kwargs["json"]["prefix"] == ""
    assert [s.filename for s in stored] == ["a.corpus"]
    assert stored[0].size_bytes == 100
    assert stored[0].repo_id == BUCKET


def test_list_owner_prefixes_and_urls(storage, session, owner):
    session.default = _resp(200, [_object("a.corpus")])
    stored = storage.list()
    _, _, kwargs = session.calls[0]
    assert kwargs["json"]["prefix"] == owner
    # filename stays bare; the object URL carries the owner path segment
    assert stored[0].filename == "a.corpus"
    assert f"/object/{BUCKET}/{owner}/a.corpus" in stored[0].url


def test_list_filters_placeholders_and_non_corpus(storage, session):
    session.default = _resp(
        200,
        [
            _object("a.corpus"),
            _object("notes.txt"),
            _object("folder", with_id=False),
        ],
    )
    assert [s.filename for s in storage.list()] == ["a.corpus"]


def test_list_missing_bucket_is_empty(storage, session):
    session.default = _resp(404, text="Bucket not found")
    assert storage.list() == []


def test_list_server_error_maps_to_storage_error(storage, session):
    session.default = _resp(500, text="boom")
    with pytest.raises(StorageError):
        storage.list()


def test_info_found_and_missing(storage, session):
    session.default = _resp(200, [_object("a.corpus")])
    assert storage.info("a").filename == "a.corpus"
    with pytest.raises(CorpusNotFoundError):
        storage.info("missing")


def test_auth_headers_sent(storage, session):
    session.default = _resp(200, [])
    storage.list()
    _, _, kwargs = session.calls[0]
    assert kwargs["headers"]["Authorization"] == f"Bearer {KEY}"
    assert kwargs["headers"]["apikey"] == KEY


# ── upload ─────────────────────────────────────────────────────────────────────


def test_upload_owner_scoped_path(storage, session, owner, tmp_path):
    archive = tmp_path / "demo.corpus"
    archive.write_bytes(b"zip")
    session.responses = {
        "/bucket": _resp(200),
        f"/{owner}/demo.corpus": _resp(200),
        f"/list/{BUCKET}": _resp(200, [_object("demo.corpus", size=3)]),
    }
    stored = storage.upload(archive)
    upload_call = next(c for c in session.calls if c[1].endswith(f"/{owner}/demo.corpus"))
    assert upload_call[0] == "post"
    assert upload_call[2]["headers"]["x-upsert"] == "true"
    assert stored.filename == "demo.corpus"


def test_upload_sanitizes_filename(storage, session, tmp_path):
    archive = tmp_path / "demo.corpus"
    archive.write_bytes(b"zip")
    session.responses = {"/list/" + BUCKET: _resp(200, [_object("evil.corpus")])}
    storage.upload(archive, filename="../../evil")
    upload_call = next(
        c for c in session.calls if c[0] == "post" and "/object/" in c[1] and "/list/" not in c[1]
    )
    assert upload_call[1].endswith(f"/object/{BUCKET}/evil.corpus")


def test_upload_missing_file_raises(storage, session, tmp_path):
    with pytest.raises(StorageError):
        storage.upload(tmp_path / "nope.corpus")
    assert session.calls == []


def test_upload_failure_maps_to_storage_error(storage, session, tmp_path):
    archive = tmp_path / "demo.corpus"
    archive.write_bytes(b"zip")
    session.responses = {"/demo.corpus": _resp(500, text="denied")}
    with pytest.raises(StorageError):
        storage.upload(archive)


def test_read_only_refuses_writes(storage, session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "hf_read_only", True)
    archive = tmp_path / "demo.corpus"
    archive.write_bytes(b"zip")
    with pytest.raises(ReadOnlyStorageError):
        storage.upload(archive)
    with pytest.raises(ReadOnlyStorageError):
        storage.delete("demo")
    assert session.calls == []


# ── download / delete ──────────────────────────────────────────────────────────


def test_download_owner_scoped(storage, session, owner, tmp_path):
    session.responses = {f"/{owner}/a.corpus": _resp(200)}
    dest = storage.download("a", dest_dir=tmp_path)
    assert dest == tmp_path / "a.corpus"
    assert dest.read_bytes() == b"corpus-bytes"
    method, url, _ = session.calls[0]
    assert method == "get"
    assert url.endswith(f"/object/{BUCKET}/{owner}/a.corpus")


def test_download_missing_maps_to_not_found(storage, session, tmp_path):
    session.default = _resp(404, text="Object not found")
    with pytest.raises(CorpusNotFoundError):
        storage.download("a", dest_dir=tmp_path)


def test_delete_owner_scoped(storage, session, owner):
    session.default = _resp(200, {"message": "ok"})
    storage.delete("a")
    method, url, _ = session.calls[0]
    assert method == "delete"
    assert url.endswith(f"/object/{BUCKET}/{owner}/a.corpus")


def test_delete_missing_maps_to_not_found(storage, session):
    session.default = _resp(400, text="Object not found")
    with pytest.raises(CorpusNotFoundError):
        storage.delete("a")


# ── ensure_repo ────────────────────────────────────────────────────────────────


def test_ensure_repo_creates_private_bucket(storage, session):
    session.default = _resp(200, {"name": BUCKET})
    storage.ensure_repo()
    method, url, kwargs = session.calls[0]
    assert url == f"{URL}/storage/v1/bucket"
    assert kwargs["json"] == {"id": BUCKET, "name": BUCKET, "public": False}


def test_ensure_repo_already_exists_is_ok(storage, session):
    session.default = _resp(409, text="The resource already exists")
    storage.ensure_repo()  # no raise


def test_ensure_repo_failure_raises(storage, session):
    session.default = _resp(500, text="boom")
    with pytest.raises(StorageError):
        storage.ensure_repo()


# ── factory + owner-scoped detail cache ────────────────────────────────────────


def test_factory_selects_backend(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "huggingface")
    assert isinstance(make_corpus_storage(), CorpusStorage)
    monkeypatch.setattr(settings, "storage_backend", "supabase")
    supabase = make_corpus_storage()
    assert isinstance(supabase, SupabaseCorpusStorage)
    assert supabase.scopes_by_owner is True
    assert CorpusStorage.scopes_by_owner is False


def test_detail_cache_key_scopes_by_owner(monkeypatch, session):
    monkeypatch.setattr(
        corpus_detail,
        "corpus_storage",
        SupabaseCorpusStorage(bucket=BUCKET, url=URL, key=KEY, session=session),
    )
    assert corpus_detail._cache_key("a.corpus") == "a.corpus"  # anonymous
    token = current_owner.set("user@!/123")
    try:
        assert corpus_detail._cache_key("a.corpus") == "user---123__a.corpus"
    finally:
        current_owner.reset(token)


def test_detail_cache_key_plain_for_hub_backend(monkeypatch):
    monkeypatch.setattr(corpus_detail, "corpus_storage", CorpusStorage())
    token = current_owner.set("user-123")
    try:
        assert corpus_detail._cache_key("a.corpus") == "a.corpus"
    finally:
        current_owner.reset(token)
