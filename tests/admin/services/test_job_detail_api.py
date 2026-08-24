"""GET /convert/{job_id}/{manifest,index,sections,content,nodes,versions}:

Job-scoped corpus-detail reads — same response shapes as the Hub-backed
``/storage/{filename}/…`` surface, but the archive is the conversion job's
on-disk result (no Hub download). 404 for an unknown / foreign job id, 409
unless the job succeeded.
"""

from pathlib import Path

import pytest
from admin.converters._text_to_tf import convert_text_to_tf
from admin.converters.convert_to_corpus import convert_to_corpus
from admin.services import corpus_detail
from admin.services.jobs import JobStatus


def _build_archive(work: Path) -> Path:
    """Build a real 5-paragraph .corpus archive and return its path."""
    work.mkdir(parents=True, exist_ok=True)
    src = work / "mini.txt"
    src.write_text(
        "\n\n".join(f"Paragraph number {i} has some words here." for i in range(1, 6))
    )
    tf_dir = convert_text_to_tf(str(src), work / "tf")
    return convert_to_corpus(
        tf_dir,
        work / "mini.corpus",
        name="Mini Corpus",
        description="A test corpus",
        language="English",
        language_code="en",
    )


@pytest.fixture
def succeeded_job(client, manager, tmp_path, monkeypatch):
    """Submit a job, then flip it to SUCCEEDED with a real .corpus result."""
    archive = _build_archive(tmp_path / "build")
    job_id = client.post(
        "/convert",
        files={"file": ("mini.txt", b"placeholder")},
        data={"source_format": "plain", "name": "Mini Corpus"},
    ).json()["job_id"]
    job = manager.get(job_id)
    job.status = JobStatus.SUCCEEDED
    job.result_path = archive

    # Reset corpus_detail cache so job-scoped reads re-extract cleanly.
    monkeypatch.setattr(corpus_detail, "_cache", {})
    monkeypatch.setattr(corpus_detail, "_local_archives", {})
    monkeypatch.setattr(corpus_detail, "_HUB_CACHE_ROOT", tmp_path / "detail-cache")
    return job_id


# ── Gating ────────────────────────────────────────────────────────────────────


def test_unknown_job_404(client):
    assert client.get("/convert/nope/manifest").status_code == 404


def test_non_succeeded_job_409(client, manager):
    job_id = client.post(
        "/convert",
        files={"file": ("mini.txt", b"placeholder")},
        data={"source_format": "plain", "name": "Mini"},
    ).json()["job_id"]
    # Job is still QUEUED (DeferredExecutor never runs the pipeline).
    assert client.get(f"/convert/{job_id}/manifest").status_code == 409


# ── Response shapes (match /storage/{filename}/…) ─────────────────────────────


def test_job_manifest(client, succeeded_job):
    body = client.get(f"/convert/{succeeded_job}/manifest").json()
    assert body["name"] == "Mini Corpus"
    assert body["format"] == "corpus"


def test_job_index(client, succeeded_job):
    body = client.get(f"/convert/{succeeded_job}/index").json()
    assert isinstance(body["node_types"], list)
    assert any(row["type"] == "word" for row in body["node_types"])
    assert "sections" in body


def test_job_sections(client, succeeded_job):
    body = client.get(f"/convert/{succeeded_job}/sections").json()
    assert body["total"] >= 1
    assert all("ref" in item for item in body["items"])


def test_job_content(client, succeeded_job):
    body = client.get(
        f"/convert/{succeeded_job}/content", params={"limit": 2}
    ).json()
    assert len(body["passages"]) == 2
    assert all(set(p) >= {"node", "ref", "text", "tokens"} for p in body["passages"])


def test_job_node(client, succeeded_job):
    content = client.get(
        f"/convert/{succeeded_job}/content", params={"limit": 1}
    ).json()
    node = content["passages"][0]["node"]
    body = client.get(f"/convert/{succeeded_job}/nodes/{node}").json()
    assert body["node"] == node
    assert isinstance(body["context"], list)
    assert body["occurrences"] >= 1


def test_job_versions(client, succeeded_job):
    body = client.get(f"/convert/{succeeded_job}/versions").json()
    assert isinstance(body["versions"], list)
    assert body["versions"]  # at least one row
    row = body["versions"][0]
    assert row["current"] is True
    assert row["id"] == "v1.0"
    assert {f["path"] for f in row["files"]} >= {"manifest.yml", "toc.yml", "corpora/"}
    assert "author" in row
