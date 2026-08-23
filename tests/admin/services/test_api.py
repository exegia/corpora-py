"""POST/GET /convert: upload hardening, status codes, ownership scoping."""

import io
from pathlib import Path

import pytest
from admin.services import api as api_module
from admin.services.jobs import JobStatus


class FakeUpload:
    """Minimal stand-in for fastapi.UploadFile (async chunked reads)."""

    def __init__(self, filename, content: bytes):
        self.filename = filename
        self._buffer = io.BytesIO(content)

    async def read(self, size: int) -> bytes:
        return self._buffer.read(size)


def _post(client, filename="doc.txt", source_format="plain", content=b"hello world"):
    return client.post(
        "/convert",
        files={"file": (filename, content)},
        data={"source_format": source_format, "name": "My Doc"},
    )


class TestCreateConversion:
    def test_valid_upload_returns_202_with_urls(self, client, manager):
        response = _post(client)
        assert response.status_code == 202
        body = response.json()
        job_id = body["job_id"]
        assert body["status_url"] == f"/convert/{job_id}"
        assert body["ws_url"] == f"/convert/{job_id}/ws"
        assert manager.get(job_id).status == JobStatus.QUEUED

    def test_owner_recorded_from_sub_claim(self, client, manager, claims_holder):
        claims_holder["claims"] = {"sub": "alice"}
        job_id = _post(client).json()["job_id"]
        assert manager.get(job_id).owner == "alice"

    def test_no_claims_means_no_owner(self, client, manager):
        job_id = _post(client).json()["job_id"]
        assert manager.get(job_id).owner is None

    def test_xml_has_no_converter_422(self, client):
        response = _post(client, source_format="xml")
        assert response.status_code == 422
        assert "No converter registered" in response.json()["detail"]

    def test_unknown_format_rejected_by_validation(self, client):
        assert _post(client, source_format="docx").status_code == 422

    def test_queue_full_returns_429_and_cleans_work_dir(self, client, manager, tmp_path):
        manager._max_pending = 1
        assert _post(client).status_code == 202
        response = _post(client)
        assert response.status_code == 429
        # Only the accepted job's work dir remains.
        work_dirs = list((tmp_path / "work").iterdir())
        assert len(work_dirs) == 1


class TestUploadFilenameHardening:
    def test_path_traversal_stripped_to_basename(self, client, manager, tmp_path):
        response = _post(client, filename="../../etc/passwd")
        assert response.status_code == 202
        work = tmp_path / "work"
        saved = list(work.rglob("passwd"))
        assert len(saved) == 1
        assert saved[0].is_relative_to(work)  # never escaped the work root
        assert not (tmp_path / "etc").exists()

    # "." / ".." / empty filenames never survive the multipart transport
    # (httpx/starlette normalize them), so the guard in _save_upload is
    # exercised directly with a fake UploadFile below.

    async def test_dotdot_filename_rejected_422(self, tmp_path):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            await api_module._save_upload(FakeUpload("..", b"x"), tmp_path / "dest")
        assert excinfo.value.status_code == 422

    async def test_dot_filename_falls_back_to_source(self, tmp_path):
        # Path(".").name is "" -- caught by the `or "source"` fallback, so a
        # bare "." never reaches the 422 guard.
        dest = await api_module._save_upload(FakeUpload(".", b"x"), tmp_path / "d")
        assert dest.name == "source"

    async def test_none_filename_defaults_to_source(self, tmp_path):
        dest = await api_module._save_upload(FakeUpload(None, b"data"), tmp_path / "d")
        assert dest.name == "source"
        assert dest.read_bytes() == b"data"

    async def test_traversal_filename_stripped_in_save_upload(self, tmp_path):
        dest = await api_module._save_upload(
            FakeUpload("../../etc/passwd", b"x"), tmp_path / "d"
        )
        assert dest == tmp_path / "d" / "passwd"


class TestUploadSizeCap:
    def test_oversized_upload_413_and_partial_unlinked(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(api_module, "_MAX_UPLOAD_BYTES", 10)
        response = _post(client, content=b"x" * 64)
        assert response.status_code == 413
        assert "MiB limit" in response.json()["detail"]
        # partial file removed AND work dir cleaned by the broad except
        assert list((tmp_path / "work").iterdir()) == []

    def test_upload_at_exact_cap_accepted(self, client, monkeypatch):
        monkeypatch.setattr(api_module, "_MAX_UPLOAD_BYTES", 11)
        assert _post(client, content=b"hello world").status_code == 202


class TestGetConversion:
    def test_unknown_job_404(self, client):
        response = client.get("/convert/nope")
        assert response.status_code == 404
        assert response.json()["detail"] == "Unknown job id"

    def test_own_job_visible(self, client, claims_holder):
        claims_holder["claims"] = {"sub": "alice"}
        job_id = _post(client).json()["job_id"]
        response = client.get(f"/convert/{job_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        assert "owner" not in response.json()

    def test_other_users_job_404_same_as_unknown(self, client, claims_holder):
        claims_holder["claims"] = {"sub": "alice"}
        job_id = _post(client).json()["job_id"]
        claims_holder["claims"] = {"sub": "mallory"}
        response = client.get(f"/convert/{job_id}")
        assert response.status_code == 404
        # identical body to the unknown-id case -- no enumeration oracle
        assert response.json() == client.get("/convert/nope").json()

    def test_ownerless_job_visible_to_authenticated_user(self, client, claims_holder):
        job_id = _post(client).json()["job_id"]  # submitted with auth off
        claims_holder["claims"] = {"sub": "anyone"}
        assert client.get(f"/convert/{job_id}").status_code == 200


class TestDownload:
    def test_not_finished_409(self, client, manager):
        job_id = _post(client).json()["job_id"]
        response = client.get(f"/convert/{job_id}/download")
        assert response.status_code == 409
        assert "queued" in response.json()["detail"]

    def test_succeeded_job_serves_file(self, client, manager, tmp_path):
        job_id = _post(client).json()["job_id"]
        result = tmp_path / "results" / "done.corpus"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_bytes(b"corpus-bytes")
        job = manager.get(job_id)
        job.status = JobStatus.SUCCEEDED
        job.result_path = result
        response = client.get(f"/convert/{job_id}/download")
        assert response.status_code == 200
        assert response.content == b"corpus-bytes"

    def test_download_content_disposition_uses_slug_filename(self, client, manager, tmp_path):
        """The Save-As filename is the slug from `name`, not the on-disk
        `result_path.name` -- so the client's library never persists the
        server-internal `job-<uuid>` id (issue #108)."""
        job_id = _post(client).json()["job_id"]
        # Simulate a server-internal on-disk name that does NOT match the slug
        # the client should see, and a user-supplied name with mixed case and
        # spaces -- the slugifier has to reduce "Summa Theologiae 1200 ENG"
        # to "summa-theologiae-1200-eng.corpus" in Content-Disposition.
        result = tmp_path / "results" / "job-abc-123.corpus"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_bytes(b"x")
        job = manager.get(job_id)
        job.name = "Summa Theologiae 1200 ENG"
        job.status = JobStatus.SUCCEEDED
        job.result_path = result
        response = client.get(f"/convert/{job_id}/download")
        assert response.status_code == 200
        # `Content-Disposition` carries the slug from the user-supplied name,
        # not `job-abc-123.corpus` (the on-disk filename).
        cd = response.headers.get("content-disposition", "")
        assert "summa-theologiae-1200-eng.corpus" in cd
        assert "job-abc-123" not in cd

    def test_download_media_type_is_zip(self, client, manager, tmp_path):
        """A `.corpus` archive is a zip; the media type reflects that so
        browsers treat the download as a saveable file, not raw bytes."""
        job_id = _post(client).json()["job_id"]
        result = tmp_path / "results" / "done.corpus"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_bytes(b"PK\x03\x04")
        job = manager.get(job_id)
        job.status = JobStatus.SUCCEEDED
        job.result_path = result
        response = client.get(f"/convert/{job_id}/download")
        assert response.headers["content-type"] == "application/zip"

    def test_unknown_job_download_404(self, client):
        assert client.get("/convert/nope/download").status_code == 404


class TestRunConversion:
    def test_work_dir_cleaned_even_on_failure(self, tmp_path, monkeypatch, manager):
        work_dir = tmp_path / "work" / "job-x"
        (work_dir / "source").mkdir(parents=True)
        source = work_dir / "source" / "doc.txt"
        source.write_text("content")

        def failing_converter(src, out):
            raise RuntimeError("converter exploded")

        monkeypatch.setitem(
            api_module.CONVERTERS, api_module.SourceFormat.PLAIN, failing_converter
        )
        try:
            api_module._run_conversion(
                source_path=source,
                work_dir=work_dir,
                source_format=api_module.SourceFormat.PLAIN,
                name="n",
                description="",
                job_id="j",
            )
        except RuntimeError:
            pass
        assert not work_dir.exists()

    def test_success_writes_corpus_to_results_root(self, tmp_path, monkeypatch, manager):
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-y"
        (work_dir / "source").mkdir(parents=True)
        source = work_dir / "source" / "doc.txt"
        source.write_text("content")

        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.PLAIN,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        # The on-disk filename is now slugified from `name` (issue #108),
        # not derived from the work_dir's tempfile name -- so a `name="n"`
        # produces `n.corpus`, not `job-y.corpus`.
        result = api_module._run_conversion(
            source_path=source,
            work_dir=work_dir,
            source_format=api_module.SourceFormat.PLAIN,
            name="n",
            description="",
            job_id="j",
        )
        assert result == tmp_path / "results" / "n.corpus"
        assert not work_dir.exists()

    def test_slugifies_corpus_filename_from_name(self, tmp_path, monkeypatch, manager):
        """A free-form `name` is reduced to a flat, safe `.corpus` filename."""
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-slug"
        (work_dir / "source").mkdir(parents=True)
        (work_dir / "source" / "doc.txt").write_text("content")
        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.PLAIN,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=work_dir / "source" / "doc.txt",
            work_dir=work_dir,
            source_format=api_module.SourceFormat.PLAIN,
            name="Summa Theologiae 1200 ENG",
            description="",
            job_id="j",
        )
        assert result.name == "summa-theologiae-1200-eng.corpus"

    def test_empty_name_falls_back_to_job_id(self, tmp_path, monkeypatch, manager):
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-empty"
        (work_dir / "source").mkdir(parents=True)
        (work_dir / "source" / "doc.txt").write_text("content")
        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.PLAIN,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=work_dir / "source" / "doc.txt",
            work_dir=work_dir,
            source_format=api_module.SourceFormat.PLAIN,
            name="",
            description="",
            job_id="fixed-id",
        )
        assert result.name == "fixed-id.corpus"

    def test_collision_appends_short_suffix(self, tmp_path, monkeypatch, manager):
        """Two jobs with the same `name` keep unique on-disk files."""
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        (tmp_path / "results").mkdir(parents=True)
        # Pre-existing file at the slug-derived path simulates a sibling job
        # that already finished -- the new call must not overwrite it.
        (tmp_path / "results" / "my-doc.corpus").write_bytes(b"prior")

        work_dir = tmp_path / "work" / "job-collide"
        (work_dir / "source").mkdir(parents=True)
        (work_dir / "source" / "doc.txt").write_text("content")
        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.PLAIN,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=work_dir / "source" / "doc.txt",
            work_dir=work_dir,
            source_format=api_module.SourceFormat.PLAIN,
            name="My Doc",
            description="",
            job_id="j",
        )
        assert result.name.startswith("my-doc-")
        assert result.name.endswith(".corpus")
        assert result.name != "my-doc.corpus"
        # The prior file is untouched.
        assert (tmp_path / "results" / "my-doc.corpus").read_bytes() == b"prior"
