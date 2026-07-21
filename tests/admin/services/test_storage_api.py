"""Tests for the `/storage` HTTP endpoints (`admin.services.storage_api`).

The router's own contract is exercised with `corpus_storage` monkeypatched
to a fake -- the real Hub wrapper is covered by `test_storage.py`. Auth
gating is the combined app's `AuthMiddleware` concern, so the router is
mounted bare (job-visibility for `job_id` uploads is still covered, via
injected claims, same approach as `tests/admin/services/conftest.py`).
"""

from pathlib import Path

import pytest
from admin.services import storage_api
from admin.services.jobs import JobStatus
from admin.services.storage import (
    CorpusNotFoundError,
    StorageNotConfiguredError,
    StoredCorpus,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _stored(filename="BHSA.corpus", size=10) -> StoredCorpus:
    return StoredCorpus(
        filename=filename,
        size_bytes=size,
        repo_id="user/archives",
        url=f"https://huggingface.co/datasets/user/archives/resolve/main/{filename}",
    )


class FakeStorage:
    def __init__(self):
        self.stored = [_stored()]
        self.deleted: list[str] = []
        self.uploads: list[tuple[Path, str | None]] = []

    def list(self):
        return self.stored

    def info(self, filename):
        for s in self.stored:
            if s.filename == filename:
                return s
        raise CorpusNotFoundError(f"No corpus named {filename!r}")

    def upload(self, local_path, filename=None):
        self.uploads.append((Path(local_path), filename))
        return _stored(filename or Path(local_path).name)

    def download(self, filename, dest_dir):
        self.info(filename)
        dest = Path(dest_dir) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"zip")
        return dest

    def delete(self, filename):
        self.info(filename)
        self.deleted.append(filename)


class FakeJob:
    def __init__(self, *, owner=None, status=JobStatus.SUCCEEDED, result_path=None):
        self.name = "My Book"
        self.owner = owner
        self.status = status
        self.result_path = result_path

    def is_visible_to(self, claims):
        if self.owner is None or claims is None:
            return True
        return claims.get("sub") == self.owner


class FakeJobManager:
    def __init__(self):
        self.jobs: dict[str, FakeJob] = {}

    def get(self, job_id):
        return self.jobs.get(job_id)


@pytest.fixture
def fake_storage(monkeypatch) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(storage_api, "corpus_storage", fake)
    return fake


@pytest.fixture
def jobs(monkeypatch) -> FakeJobManager:
    mgr = FakeJobManager()
    monkeypatch.setattr(storage_api, "job_manager", mgr)
    return mgr


class ClaimsMiddleware:
    """Injects claims into scope['state'] the way AuthMiddleware would."""

    def __init__(self, app, claims_holder):
        self.app = app
        self.claims_holder = claims_holder

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.claims_holder["claims"] is not None:
            scope.setdefault("state", {})["user"] = self.claims_holder["claims"]
        await self.app(scope, receive, send)


@pytest.fixture
def client(fake_storage, jobs, claims_holder, tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(storage_api, "_HUB_CACHE_ROOT", tmp_path / "hub-cache")
    app = FastAPI()
    app.include_router(storage_api.router)
    app.add_middleware(ClaimsMiddleware, claims_holder=claims_holder)
    return TestClient(app)


def test_list(client):
    resp = client.get("/storage")
    assert resp.status_code == 200
    assert [s["filename"] for s in resp.json()] == ["BHSA.corpus"]


def test_get_info(client):
    resp = client.get("/storage/BHSA.corpus")
    assert resp.status_code == 200
    assert resp.json()["size_bytes"] == 10


def test_get_info_missing_is_404(client):
    assert client.get("/storage/absent.corpus").status_code == 404


def test_not_configured_is_503(client, fake_storage, monkeypatch):
    def boom():
        raise StorageNotConfiguredError("set HF_STORAGE_REPO")

    monkeypatch.setattr(fake_storage, "list", boom)
    resp = client.get("/storage")
    assert resp.status_code == 503


def test_upload_requires_a_source(client):
    assert client.post("/storage", json={}).status_code == 422


def test_upload_by_path(client, fake_storage, tmp_path):
    archive = tmp_path / "mini.corpus"
    archive.write_bytes(b"zip")
    resp = client.post("/storage", json={"path": str(archive)})
    assert resp.status_code == 201
    assert resp.json()["filename"] == "mini.corpus"
    assert fake_storage.uploads == [(archive, None)]


def test_upload_by_missing_path_is_404(client, tmp_path):
    resp = client.post("/storage", json={"path": str(tmp_path / "absent.corpus")})
    assert resp.status_code == 404


def test_upload_by_job_id(client, fake_storage, jobs, tmp_path):
    archive = tmp_path / "job-x.corpus"
    archive.write_bytes(b"zip")
    jobs.jobs["j1"] = FakeJob(result_path=archive)
    resp = client.post("/storage", json={"job_id": "j1"})
    assert resp.status_code == 201
    # Stored under the job's human name, not the random work-dir name.
    assert fake_storage.uploads == [(archive, "My Book.corpus")]


def test_upload_by_unknown_job_is_404(client):
    assert client.post("/storage", json={"job_id": "nope"}).status_code == 404


def test_upload_by_unfinished_job_is_409(client, jobs):
    jobs.jobs["j1"] = FakeJob(status=JobStatus.RUNNING)
    assert client.post("/storage", json={"job_id": "j1"}).status_code == 409


def test_upload_someone_elses_job_is_404(client, jobs, claims_holder, tmp_path):
    archive = tmp_path / "job-x.corpus"
    archive.write_bytes(b"zip")
    jobs.jobs["j1"] = FakeJob(owner="alice", result_path=archive)
    claims_holder["claims"] = {"sub": "bob"}

    # Same 404 as an unknown id -- foreign job ids must not be enumerable.
    assert client.post("/storage", json={"job_id": "j1"}).status_code == 404


def test_upload_own_job_succeeds_with_claims(client, jobs, claims_holder, tmp_path):
    archive = tmp_path / "job-x.corpus"
    archive.write_bytes(b"zip")
    jobs.jobs["j1"] = FakeJob(owner="alice", result_path=archive)
    claims_holder["claims"] = {"sub": "alice"}

    assert client.post("/storage", json={"job_id": "j1"}).status_code == 201


def test_download_streams_archive(client):
    resp = client.get("/storage/BHSA.corpus/download")
    assert resp.status_code == 200
    assert resp.content == b"zip"


def test_download_missing_is_404(client):
    assert client.get("/storage/absent.corpus/download").status_code == 404


def test_delete(client, fake_storage):
    resp = client.delete("/storage/BHSA.corpus")
    assert resp.status_code == 204
    assert fake_storage.deleted == ["BHSA.corpus"]


def test_delete_missing_is_404(client):
    assert client.delete("/storage/absent.corpus").status_code == 404


# ── read-only mode (HF_READ_ONLY) ─────────────────────────────────────────────
# The `require_writable` dependency rejects mutating routes with 403 up front,
# before any Hub I/O -- reads stay open.


def test_read_only_post_is_403(client, fake_storage, monkeypatch):
    monkeypatch.setattr(storage_api.settings, "hf_read_only", True)
    resp = client.post("/storage", json={"path": "/tmp/x.corpus"})
    assert resp.status_code == 403
    assert fake_storage.uploads == []


def test_read_only_delete_is_403(client, fake_storage, monkeypatch):
    monkeypatch.setattr(storage_api.settings, "hf_read_only", True)
    resp = client.delete("/storage/BHSA.corpus")
    assert resp.status_code == 403
    assert fake_storage.deleted == []


def test_read_only_still_allows_reads(client, monkeypatch):
    monkeypatch.setattr(storage_api.settings, "hf_read_only", True)
    assert client.get("/storage").status_code == 200
    assert client.get("/storage/BHSA.corpus").status_code == 200
