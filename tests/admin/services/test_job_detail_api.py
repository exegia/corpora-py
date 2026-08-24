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
    src.write_text("\n\n".join(f"Paragraph number {i} has some words here." for i in range(1, 6)))
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
    body = client.get(f"/convert/{succeeded_job}/content", params={"limit": 2}).json()
    assert len(body["passages"]) == 2
    assert all(set(p) >= {"node", "ref", "text", "tokens"} for p in body["passages"])


def test_job_node(client, succeeded_job):
    content = client.get(f"/convert/{succeeded_job}/content", params={"limit": 1}).json()
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


def test_job_two_manifest_patches_snapshot_and_bump(client, succeeded_job, manager):
    """Job-scoped PATCHes bump 1.x and snapshot each label beside HEAD (#149)."""
    first = client.patch(f"/convert/{succeeded_job}/manifest", json={"description": "A"})
    assert first.status_code == 200
    assert first.json()["version"] == "1.1"
    second = client.patch(f"/convert/{succeeded_job}/manifest", json={"description": "B"})
    assert second.status_code == 200
    assert second.json()["version"] == "1.2"

    versions = client.get(f"/convert/{succeeded_job}/versions").json()["versions"]
    assert [row["label"] for row in versions] == ["v1.0", "v1.1", "v1.2"]
    assert [row["current"] for row in versions] == [False, False, True]
    assert versions[1]["snapshot_key"] == (f"conversion-jobs/{succeeded_job}/v1.1.corpus")
    assert versions[2]["snapshot_key"] == (f"conversion-jobs/{succeeded_job}/v1.2.corpus")

    job = manager.get(succeeded_job)
    parent = Path(job.result_path).parent
    v0 = parent / f"{succeeded_job}-v1.0.corpus"
    v1 = parent / f"{succeeded_job}-v1.1.corpus"
    v2 = parent / f"{succeeded_job}-v1.2.corpus"
    assert v0.is_file() and v1.is_file() and v2.is_file()
    head = Path(job.result_path).stat().st_size
    assert head < v0.stat().st_size * 1.5
    assert client.get(f"/convert/{succeeded_job}/manifest").json()["description"] == "B"


def test_job_manifest_patch_on_queued_job_is_409(client, manager):
    job_id = client.post(
        "/convert",
        files={"file": ("mini.txt", b"placeholder")},
        data={"source_format": "plain", "name": "Mini"},
    ).json()["job_id"]
    resp = client.patch(f"/convert/{job_id}/manifest", json={"description": "x"})
    assert resp.status_code == 409


def test_job_restore_v1_after_mutations(client, succeeded_job):
    original = client.get(f"/convert/{succeeded_job}/manifest").json()["description"]
    client.patch(
        f"/convert/{succeeded_job}/manifest", json={"description": "A"}
    )
    client.patch(
        f"/convert/{succeeded_job}/manifest", json={"description": "B"}
    )
    assert (
        client.get(f"/convert/{succeeded_job}/manifest").json()["description"]
        == "B"
    )

    resp = client.post(
        f"/convert/{succeeded_job}/restore", json={"version_id": "v1.0"}
    )
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert [row["label"] for row in versions] == ["v1.0", "v1.1", "v1.2", "v1.3"]
    assert versions[-1]["current"] is True
    assert versions[-1]["title"] == "Restored v1.0"
    assert versions[0]["current"] is False

    body = client.get(f"/convert/{succeeded_job}/manifest").json()
    assert body["description"] == original
    assert body["version"] == "1.3"
    index = client.get(f"/convert/{succeeded_job}/index").json()
    assert "toc" in index


def test_job_restore_unknown_version_is_404(client, succeeded_job):
    resp = client.post(
        f"/convert/{succeeded_job}/restore", json={"version_id": "v9.9"}
    )
    assert resp.status_code == 404


def test_job_restore_current_is_409(client, succeeded_job):
    resp = client.post(
        f"/convert/{succeeded_job}/restore", json={"version_id": "v1.0"}
    )
    assert resp.status_code == 409


def test_job_restore_queued_is_409(client):
    job_id = client.post(
        "/convert",
        files={"file": ("mini.txt", b"placeholder")},
        data={"source_format": "plain", "name": "Mini"},
    ).json()["job_id"]
    resp = client.post(f"/convert/{job_id}/restore", json={"version_id": "v1.0"})
    assert resp.status_code == 409
