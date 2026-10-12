import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
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
    assert manifest.status_code == 200 and manifest.json()["format"] == "corpora-cusx-package/0.2.0"
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
        assert "Selected words." in json.loads(archive.read("snapshots/0001.json"))["text"]
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


@pytest.mark.parametrize(
    "fmt,filename,payload,documents",
    [
        ("plain", "notes.txt", "  וְחַטָּאִ֑ים é 😀\r\n\r\n end ".encode(), 1),
        ("markdown", "notes.md", "# Heading\n\n**וְחַטָּאִ֑ים** é 😀\n".encode(), 1),
        (
            "xml",
            "catalog.xml",
            '<catalog xmlns="urn:catalog"> before <item id="one">é 😀</item> after </catalog>'.encode(),
            1,
        ),
        (
            "tei",
            "edition.tei",
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><head>One</head><p>וְחַטָּאִ֑ים</p></div><div><head>Two</head><p>é 😀</p></div></body></text></TEI>'.encode(),
            2,
        ),
        ("pdf", "outlined.pdf", None, 2),
    ],
)
def test_format_api_retains_original_source_and_documents(
    client, manager, fmt, filename, payload, documents, pinned_pdf_ocr
):
    if payload is None:
        payload = (Path(__file__).parents[1] / "fixtures/cusx/outlined.pdf").read_bytes()
    response = client.post(
        "/convert",
        files={"file": (filename, payload)},
        data={
            "source_format": fmt,
            "name": "Format review",
            "output_format": "cusx",
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    manager._executor.run_all()
    status = client.get(f"/convert/{job_id}").json()
    assert status["status"] == "succeeded", status
    assert status["validation"]["valid"]
    manifest = client.get(f"/convert/{job_id}/manifest").json()
    assert len(manifest["documents"]) == documents
    download = client.get(f"/convert/{job_id}/download")
    assert download.content == manager.get(job_id).result_path.read_bytes()
    with zipfile.ZipFile(manager.get(job_id).result_path) as archive:
        assert archive.read(manifest["source"]["evidence"]) == payload
        for document in manifest["documents"]:
            assert json.loads(archive.read(document["snapshot"]))["text"]


def test_pdf_api_accepts_scan_for_forced_ocr(client, manager, tmp_path, pinned_pdf_ocr):
    source = tmp_path / "scan.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(source)
    response = client.post(
        "/convert",
        files={"file": ("scan.pdf", source.read_bytes())},
        data={
            "source_format": "pdf",
            "name": "Scan",
            "output_format": "cusx",
        },
    )
    assert response.status_code == 202, response.text
    assert manager._executor.pending


@pytest.mark.parametrize(
    "score,expected_status",
    [(49, "failed"), (50, "succeeded"), (90, "succeeded"), (91, "succeeded"), (None, "failed")],
)
def test_pdf_reliability_controls_download(
    client, manager, monkeypatch, pinned_pdf_ocr, score, expected_status
):
    from admin.services import source_reliability

    monkeypatch.setattr(
        source_reliability,
        "configured_comparison",
        lambda source, evidence: {
            "source_sha256": evidence["source_sha256"],
            "snapshot_sha256": evidence["snapshot_sha256"],
            "score_percent": score,
            "complete": score is not None,
            "method": "independent-test-review",
            "mismatches": [],
        },
    )
    monkeypatch.setattr(validation_api, "job_manager", manager)
    client.app.include_router(validation_api.router)
    payload = (Path(__file__).parents[1] / "fixtures/cusx/outlined.pdf").read_bytes()
    response = client.post(
        "/convert",
        files={"file": ("outlined.pdf", payload)},
        data={
            "source_format": "pdf",
            "name": "OCR policy",
            "output_format": "cusx",
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    manager._executor.run_all()
    status = client.get(f"/convert/{job_id}").json()
    assert status["status"] == expected_status, status
    report = status["validation"]["source_reliability"]
    assert report["score_percent"] == score
    downloaded = client.get(f"/convert/{job_id}/download")
    assert downloaded.status_code == (200 if expected_status == "succeeded" else 409)
    if expected_status == "succeeded":
        rechecked = client.post("/validate", json={"job_id": job_id}).json()
        assert rechecked["source_reliability"] == report
