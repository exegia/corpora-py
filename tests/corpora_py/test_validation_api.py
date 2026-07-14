"""Tests for the `/validate` HTTP endpoint (`admin.services.validation_api`).

The endpoint's own contract is exercised here with the underlying
`validate_corpus` function monkeypatched to canned results -- the actual
`.tf -> .cfm -> mmap` cycle is covered by `tests/mcp/test_validate.py`. Auth
gating is the combined app's `AuthMiddleware` concern (see
`tests/corpora_py/test_auth_middleware.py`), so the router is mounted bare here.
"""

import pytest
from admin.services import validation_api
from admin.services.validation_api import router
from corpora_mcp.validate import CorpusStats, ValidationResult
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _stats(**overrides: object) -> CorpusStats:
    base: dict = dict(max_slot=6, max_node=8, node_types=2, node_features=3, edge_features=1)
    base.update(overrides)
    return CorpusStats(**base)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _patch_validate(monkeypatch, result: ValidationResult):
    monkeypatch.setattr(validation_api, "validate_corpus", lambda name, path: result)


def test_validate_path_valid(client, tmp_path, monkeypatch):
    corpus_dir = tmp_path / "mini"
    corpus_dir.mkdir()
    _patch_validate(
        monkeypatch,
        ValidationResult(
            corpus="mini", tf_stats=None, cf_stats=_stats(), cf_mmap_stats=_stats()
        ),
    )

    resp = client.post("/validate", json={"path": str(corpus_dir)})

    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["corpus"] == "mini"
    assert body["path"] == str(corpus_dir)
    assert body["stats"]["max_slot"] == 6
    assert body["reasons"] == []


def test_validate_file_path_dispatches_to_archive(client, tmp_path, monkeypatch):
    archive = tmp_path / "mini.corpus"
    archive.write_bytes(b"PK\x03\x04 placeholder")  # exists + is a file
    result = ValidationResult(
        corpus="Archived Mini",
        tf_stats=None,
        cf_stats=_stats(),
        cf_mmap_stats=_stats(),
        shipped_cfm_stats=_stats(),
    )
    seen: dict = {}

    def fake_archive(path, name=None):
        seen["path"] = path
        return result

    monkeypatch.setattr(
        validation_api,
        "validate_corpus",
        lambda *a, **k: pytest.fail("directory validator used for a file path"),
    )
    monkeypatch.setattr(validation_api, "validate_corpus_archive", fake_archive)

    resp = client.post("/validate", json={"path": str(archive)})

    assert resp.status_code == 200
    body = resp.json()
    assert body["corpus"] == "Archived Mini"  # from the archive manifest
    assert body["valid"] is True
    assert body["checks"]["shipped_cfm_load"] is True
    assert str(seen["path"]) == str(archive)


def test_validate_path_invalid_returns_200_with_reasons(client, tmp_path, monkeypatch):
    corpus_dir = tmp_path / "mini"
    corpus_dir.mkdir()
    _patch_validate(
        monkeypatch,
        ValidationResult(
            corpus="mini",
            tf_stats=None,
            cf_stats=CorpusStats(error="cannot parse otype.tf"),
            cf_mmap_stats=CorpusStats(error="no cache"),
        ),
    )

    resp = client.post("/validate", json={"path": str(corpus_dir)})

    # An invalid corpus is a result, not a bad request.
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["stats"] is None
    assert any("cannot parse otype.tf" in r for r in body["reasons"])


def test_validate_missing_path_is_404(client, tmp_path):
    resp = client.post("/validate", json={"path": str(tmp_path / "does-not-exist")})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_validate_unknown_corpus_is_404(client, monkeypatch):
    def _raise(name=None):
        raise KeyError("Corpus 'nope' not found. Loaded: []")

    monkeypatch.setattr(validation_api.corpus_manager, "get_path", _raise)

    resp = client.post("/validate", json={"corpus": "nope"})
    assert resp.status_code == 404


def test_validate_by_corpus_name_resolves_path(client, tmp_path, monkeypatch):
    corpus_dir = tmp_path / "loaded"
    corpus_dir.mkdir()
    monkeypatch.setattr(
        validation_api.corpus_manager, "get_path", lambda name=None: corpus_dir
    )
    _patch_validate(
        monkeypatch,
        ValidationResult(
            corpus="loaded", tf_stats=None, cf_stats=_stats(), cf_mmap_stats=_stats()
        ),
    )

    resp = client.post("/validate", json={"corpus": "loaded"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["corpus"] == "loaded"
    assert body["path"] == str(corpus_dir)
    assert body["valid"] is True


# ── job_id resolution ────────────────────────────────────────────────────────


class _FakeJob:
    """Just enough of ConversionJob for _resolve_job_target: status,
    result_path, name, and the visibility check."""

    def __init__(self, *, status, result_path, name="converted-job", visible=True):
        self.status = status
        self.result_path = result_path
        self.name = name
        self._visible = visible

    def is_visible_to(self, claims):
        return self._visible


def _patch_job(monkeypatch, job):
    monkeypatch.setattr(validation_api.job_manager, "get", lambda job_id: job)


def test_validate_by_job_id_validates_result_archive(client, tmp_path, monkeypatch):
    from admin.services.jobs import JobStatus

    archive = tmp_path / "job-abc.corpus"
    archive.write_bytes(b"PK\x03\x04 placeholder")
    _patch_job(
        monkeypatch, _FakeJob(status=JobStatus.SUCCEEDED, result_path=archive)
    )
    result = ValidationResult(
        corpus="converted-job",
        tf_stats=None,
        cf_stats=_stats(),
        cf_mmap_stats=_stats(),
        shipped_cfm_stats=_stats(),
    )
    monkeypatch.setattr(
        validation_api, "validate_corpus_archive", lambda path, name=None: result
    )

    resp = client.post("/validate", json={"job_id": "abc"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["path"] == str(archive)


def test_validate_unknown_job_id_is_404(client, monkeypatch):
    _patch_job(monkeypatch, None)
    resp = client.post("/validate", json={"job_id": "nope"})
    assert resp.status_code == 404


def test_validate_invisible_job_is_404_like_unknown(client, tmp_path, monkeypatch):
    from admin.services.jobs import JobStatus

    archive = tmp_path / "someone-elses.corpus"
    archive.write_bytes(b"PK\x03\x04")
    _patch_job(
        monkeypatch,
        _FakeJob(status=JobStatus.SUCCEEDED, result_path=archive, visible=False),
    )

    resp = client.post("/validate", json={"job_id": "abc"})

    # Same 404 as an unknown id -- no job-id enumeration via /validate.
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Unknown job id"


def test_validate_unfinished_job_is_409(client, monkeypatch):
    from admin.services.jobs import JobStatus

    _patch_job(monkeypatch, _FakeJob(status=JobStatus.RUNNING, result_path=None))

    resp = client.post("/validate", json={"job_id": "abc"})

    assert resp.status_code == 409
    assert "not ready" in resp.json()["detail"]
