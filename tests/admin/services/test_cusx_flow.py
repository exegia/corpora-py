import json
import zipfile

from admin.parsers.schema import SourceFormat
from admin.services import storage_api, validation_api
from admin.services.jobs import ConversionJob, JobStatus


def test_convert_validate_download_publish_same_cusx_bytes(client, manager, monkeypatch, tmp_path):
    # Real conversion and archive validation; only the remote Hub is replaced.
    monkeypatch.setattr(storage_api, "job_manager", manager)
    monkeypatch.setattr(validation_api, "job_manager", manager)
    uploads = []

    class Storage:
        def upload(self, path, filename):
            from admin.services.storage import StoredCorpus

            uploads.append((filename, path.read_bytes()))
            return StoredCorpus(
                filename, path.stat().st_size, "test/bucket", "https://example.test/file"
            )

    monkeypatch.setattr(storage_api, "corpus_storage", Storage())
    # Keep the existing write capability dependency local to the test.
    client.app.dependency_overrides[storage_api.require_writable] = lambda: None
    client.app.include_router(validation_api.router)
    client.app.include_router(storage_api.router)
    response = client.post(
        "/convert",
        files={"file": ("notes.txt", "😀 Selected words.")},
        data={"source_format": "plain", "name": "Notes", "output_format": "cusx"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    manager._executor.run_all()
    status = client.get(f"/convert/{job_id}").json()
    assert status["status"] == "succeeded", status
    assert status["result_filename"].endswith(".cusx")
    assert status["validation"]["valid"]
    manifest = client.get(f"/convert/{job_id}/manifest")
    assert manifest.status_code == 200 and manifest.json()["format"] == "corpora-cusx-package/0.1.0"
    graph = client.get(f"/convert/{job_id}/index")
    assert graph.status_code == 422 and "Text-Fabric" in graph.json()["detail"]
    downloaded = client.get(f"/convert/{job_id}/download")
    assert downloaded.status_code == 200
    assert ".cusx" in downloaded.headers["content-disposition"]
    assert client.post("/validate", json={"job_id": job_id}).json()["valid"]
    published = client.post("/storage", json={"job_id": job_id})
    assert published.status_code == 201, published.text
    assert uploads == [(status["result_filename"], downloaded.content)]
    with zipfile.ZipFile(manager.get(job_id).result_path) as archive:
        assert "Selected words." in json.loads(archive.read("snapshot.json"))["text"]
    from admin.services.corpus_detail import read_archive

    assert read_archive(manager.get(job_id).result_path, "manifest") == manifest.json()


def test_remote_job_filename_preserves_cusx_without_new_columns():
    job = ConversionJob(
        id="test",
        source_format=SourceFormat.PLAIN,
        name="Notes",
        status=JobStatus.SUCCEEDED,
        result_key="conversion-jobs/test.cusx",
    )
    assert job.to_dict()["result_filename"] == "notes.cusx"


def test_unsupported_output_rejected_before_job_creation(client, manager):
    response = client.post(
        "/convert",
        files={"file": ("notes.txt", b"words")},
        data={"source_format": "plain", "name": "Notes", "output_format": "invented"},
    )
    assert response.status_code == 422
    assert not manager._executor.pending
