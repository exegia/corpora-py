"""Real HTTP-to-CTEI jobs, typed history and local/remote snapshots."""

import io
import zipfile

import pytest
import yaml
from admin.parsers.schema import SourceFormat
from admin.services.job_store_supabase import job_from_row, job_to_row
from admin.services.jobs import ConversionJob, LocalResultStore, snapshot_key_for


def test_real_upload_poll_download_manifest_and_versions(client, manager, claims_holder):
    claims_holder["claims"] = {"sub": "user-123"}
    response = client.post(
        "/convert",
        data={"source_format": "plain", "name": "The Document", "output_format": "ctei"},
        files={"file": ("input.txt", "Greek: ἄνθρωπος é.\n\nNext.", "text/plain")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    queued = client.get(f"/convert/{job_id}").json()
    assert queued["output_format"] == "ctei"
    assert queued["result_filename"].endswith(".ctei")
    assert not queued["download_ready"]
    manager._executor.run_all()
    complete = client.get(f"/convert/{job_id}").json()
    assert complete["status"] == "succeeded", complete.get("error")
    assert complete["validation"]["valid"]
    result = client.get(f"/convert/{job_id}/download")
    assert result.status_code == 200
    assert result.headers["content-type"] == "application/zip"
    assert ".ctei" in result.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(result.content)) as zf:
        manifest = yaml.safe_load(zf.read("manifest.yml"))
        assert manifest["name"] == "The Document"
        assert "review.xml" in zf.namelist()
        assert "history.xml" in zf.namelist()
    assert client.get(f"/convert/{job_id}/manifest").json() == manifest
    row = client.get(f"/convert/{job_id}/versions").json()["versions"][0]
    assert row["author"] == {"sub": "user-123"}
    key = snapshot_key_for(job_id, row["label"], ".ctei")
    assert manager.materialize_snapshot(job_id, key).suffix == ".ctei"
    assert client.patch(f"/convert/{job_id}/manifest", json={"name": "Edited"}).status_code == 409
    assert client.get(f"/convert/{job_id}/content").status_code == 409


@pytest.mark.parametrize("format", ["tei", "invalid", "cusx"])
def test_output_format_enum_rejects_invalid_targets(client, format):
    response = client.post(
        "/convert",
        data={"source_format": "plain", "name": "Test", "output_format": format},
        files={"file": ("input.txt", "Text", "text/plain")},
    )
    assert response.status_code == 422


def test_ctei_job_row_preserves_target_across_instances():
    job = ConversionJob(
        id="job-a", source_format=SourceFormat.PLAIN, name="Greek", output_format="ctei"
    )
    row = job_to_row(job)
    restored = job_from_row(row)
    assert restored.to_dict()["output_format"] == "ctei"
    assert restored.to_dict()["result_filename"] == "greek.ctei"
    row.pop("output_format")
    assert job_from_row(row).output_format == "corpus"


@pytest.mark.parametrize("suffix", [".corpus", ".ctei"])
def test_snapshot_extension_and_local_reload(tmp_path, suffix):
    source = tmp_path / ("source" + suffix)
    source.write_bytes(b"archive bytes")
    cache = tmp_path / "snapshots"
    store = LocalResultStore(cache)
    key = store.save_snapshot("job-a", source, "v1.0")
    assert key == "conversion-jobs/job-a/v1.0" + suffix
    reloaded = LocalResultStore(cache)
    assert reloaded.materialize(key, "job-a").read_bytes() == b"archive bytes"
    assert reloaded.materialize(key, "job-a").suffix == suffix
    assert snapshot_key_for("job-a", "v1.0", ".txt") is None


def test_openapi_declares_ctei(client):
    spec = client.get("/openapi.json").json()
    schema = next(
        s
        for s in spec["components"]["schemas"].values()
        if "output_format" in s.get("properties", {}) and "file" in s["properties"]
    )
    assert schema["properties"]["output_format"]["enum"] == ["corpus", "ctei"]


def test_malformed_ctei_history_returns_metadata_error(client, manager):
    response = client.post(
        "/convert",
        data={"source_format": "plain", "name": "Test", "output_format": "ctei"},
        files={"file": ("input.txt", "Text", "text/plain")},
    )
    job_id = response.json()["job_id"]
    manager._executor.run_all()
    archive = manager.get(job_id).result_path
    with zipfile.ZipFile(archive) as zf:
        members = {name: zf.read(name) for name in zf.namelist()}
    members["history.xml"] = b"<history><broken>"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    result = client.get(f"/convert/{job_id}/versions")
    assert result.status_code == 422
    assert result.json()["detail"] == "CTEI archive metadata is invalid"


@pytest.mark.asyncio
async def test_vercel_response_keeps_worker_alive_until_terminal_write(client, monkeypatch, tmp_path):
    import asyncio
    import json
    from threading import Event

    import httpx
    from admin.services import api as api_module
    from admin.services.jobs import JobManager, JobStatus

    monkeypatch.setenv("VERCEL", "1")
    live_manager = JobManager(max_workers=1)
    monkeypatch.setattr(api_module, "job_manager", live_manager)
    entered, release = Event(), Event()
    output = tmp_path / "completed.ctei"
    output.write_bytes(b"controlled worker output")

    def conversion(**kwargs):
        entered.set()
        assert release.wait(5), "worker was never released"
        return output

    monkeypatch.setattr(api_module, "_run_conversion", conversion)
    request = httpx.Request(
        "POST", "http://testserver/convert",
        data={"source_format": "plain", "name": "Test", "output_format": "ctei"},
        files={"file": ("input.txt", "Text", "text/plain")},
    )
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/convert", "raw_path": b"/convert",
        "query_string": b"", "root_path": "", "headers": [(name.lower(), value) for name, value in request.headers.raw],
        "server": ("testserver", 80), "client": ("test", 1),
    }
    body = request.read()
    received = False
    sent = asyncio.Event()
    messages = []

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body"):
            sent.set()

    invocation = asyncio.create_task(client.app(scope, receive, send))
    try:
        await asyncio.wait_for(sent.wait(), 3)
        assert messages[0]["status"] == 202, messages
        job_id = json.loads(messages[-1]["body"])["job_id"]
        assert await asyncio.to_thread(entered.wait, 2)
        assert live_manager.get(job_id).status == JobStatus.RUNNING
        assert not invocation.done(), "ASGI invocation ended while the worker was active"
        release.set()
        await asyncio.wait_for(invocation, 5)
        assert live_manager.get(job_id).status == JobStatus.SUCCEEDED
        assert live_manager.get(job_id).result_path == output
    finally:
        release.set()
        live_manager.shutdown(wait=True)
