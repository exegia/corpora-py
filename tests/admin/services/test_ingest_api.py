"""POST/GET /ingest: Docling availability gate, input validation, job flow.

Reuses the `manager`/`client` fixtures from conftest.py (deferred executor —
no real Docling run ever happens); the parse itself is monkeypatched so these
tests exercise the HTTP surface, not the mapper (covered by
tests/admin/ingest/test_docling_graph.py).
"""

import json
import uuid

import pytest
from admin.services import ingest_api as ingest_module
from admin.services.jobs import JobStatus


class FakeGraph:
    nodes = [{"id": "n1"}]
    fragments = []

    @staticmethod
    def to_dict():
        return {"schemaVersion": "1.0.0", "nodes": FakeGraph.nodes, "fragments": []}


@pytest.fixture
def docling_available(monkeypatch):
    """Pretend the docling extra is installed and stub out the actual parse."""
    monkeypatch.setattr(ingest_module, "find_spec", lambda name: object())

    calls = {}

    def fake_parse_file(source_path, *, language, corpus_id, title):
        calls["kwargs"] = {
            "source_path": source_path,
            "language": language,
            "corpus_id": corpus_id,
            "title": title,
        }
        return FakeGraph()

    monkeypatch.setattr(ingest_module, "parse_file", fake_parse_file)
    return calls


def _post(client, data=None, filename="doc.pdf"):
    return client.post(
        "/ingest", files={"file": (filename, b"%PDF-1.7 fake")}, data=data or {}
    )


class TestCreateIngestion:
    def test_503_when_docling_not_installed(self, client, monkeypatch):
        monkeypatch.setattr(ingest_module, "find_spec", lambda name: None)
        response = _post(client)
        assert response.status_code == 503
        assert "corpora-admin[docling]" in response.json()["detail"]

    def test_valid_upload_returns_202_with_urls(self, client, manager, docling_available):
        response = _post(client)
        assert response.status_code == 202
        body = response.json()
        job_id = body["job_id"]
        assert body["status_url"] == f"/ingest/{job_id}"
        assert body["download_url"] == f"/ingest/{job_id}/download"
        job = manager.get(job_id)
        assert job.status == JobStatus.QUEUED
        assert job.source_format == "pdf"  # detected from the upload suffix

    def test_bad_language_422(self, client, docling_available):
        assert _post(client, data={"language": "not a tag!"}).status_code == 422

    def test_bad_corpus_id_422(self, client, docling_available):
        assert _post(client, data={"corpus_id": "not-a-uuid"}).status_code == 422

    def test_owner_recorded_from_sub_claim(
        self, client, manager, claims_holder, docling_available
    ):
        claims_holder["claims"] = {"sub": "alice"}
        job_id = _post(client).json()["job_id"]
        assert manager.get(job_id).owner == "alice"


class TestIngestionJobFlow:
    def test_job_runs_and_serves_graph_json(
        self, client, manager, docling_available, tmp_path
    ):
        corpus_id = str(uuid.uuid4())
        job_id = _post(
            client, data={"name": "My Doc", "language": "en", "corpus_id": corpus_id}
        ).json()["job_id"]
        manager._executor.run_all()

        kwargs = docling_available["kwargs"]
        assert kwargs["language"] == "en"
        assert kwargs["corpus_id"] == corpus_id
        assert kwargs["title"] == "My Doc"

        status = client.get(f"/ingest/{job_id}").json()
        assert status["status"] == "succeeded"
        assert status["download_ready"] is True

        download = client.get(f"/ingest/{job_id}/download")
        assert download.status_code == 200
        assert json.loads(download.content) == FakeGraph.to_dict()
        # the upload/work dir was cleaned up; only the result survives
        assert list((tmp_path / "work").iterdir()) == []

    def test_download_before_finish_409(self, client, manager, docling_available):
        job_id = _post(client).json()["job_id"]
        assert client.get(f"/ingest/{job_id}/download").status_code == 409

    def test_other_users_job_404s(
        self, client, manager, claims_holder, docling_available
    ):
        claims_holder["claims"] = {"sub": "alice"}
        job_id = _post(client).json()["job_id"]
        claims_holder["claims"] = {"sub": "mallory"}
        assert client.get(f"/ingest/{job_id}").status_code == 404
        assert client.get(f"/ingest/{job_id}/download").status_code == 404

    def test_unknown_job_404(self, client, docling_available):
        assert client.get("/ingest/nope").status_code == 404
