"""POST/GET /convert: upload hardening, status codes, ownership scoping, title derivation."""

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

    def test_xml_format_is_accepted(self, client):
        response = _post(client, source_format="xml")
        assert response.status_code == 202

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
        """The Save-As filename is `result_path.name` (the slug from the
        display name / request name, as written by `_run_conversion`), not
        a recomputed slug -- so the Content-Disposition always matches the
        `result_filename` the client already received in `to_dict()`
        (issues #108/#109)."""
        job_id = _post(client).json()["job_id"]
        # Simulate a server-internal on-disk name that does NOT match what
        # the client should see, and a display name with mixed case and
        # spaces -- the on-disk `result_path.name` is the source of truth
        # for Content-Disposition, so "summa-theologiae.corpus" (the slug
        # of the display name) appears, not "job-abc-123.corpus".
        result = tmp_path / "results" / "summa-theologiae.corpus"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_bytes(b"x")
        job = manager.get(job_id)
        job.display_name = "Summa Theologiae"
        job.status = JobStatus.SUCCEEDED
        job.result_path = result
        response = client.get(f"/convert/{job_id}/download")
        assert response.status_code == 200
        # `Content-Disposition` carries result_path.name (the slug from the
        # display name), not a recomputed slug.
        cd = response.headers.get("content-disposition", "")
        assert "summa-theologiae.corpus" in cd
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
        # Uses TF_ZIP (no parser -> no source title) so the request `name`
        # is the display_name and the archive filename is slugified from it.
        # A plain-text source would derive "doc" from the filename stem as
        # the source title (see TestRunConversionDisplayName).
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-y"
        (work_dir / "source").mkdir(parents=True)
        source = work_dir / "source" / "dataset.zip"
        source.write_bytes(b"fake zip")

        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.TF_ZIP,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=source,
            work_dir=work_dir,
            source_format=api_module.SourceFormat.TF_ZIP,
            name="n",
            description="",
            job_id="j",
        )
        assert result == tmp_path / "results" / "n.corpus"
        assert not work_dir.exists()

    def test_slugifies_corpus_filename_from_name(self, tmp_path, monkeypatch, manager):
        """A free-form `name` is reduced to a flat, safe `.corpus` filename.

        Uses TF_ZIP (no parser -> no source title) so the request `name` is
        the display_name and the slug is derived from it. A plain-text
        source would derive the filename stem as the source title instead
        (see TestRunConversionDisplayName).
        """
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-slug"
        (work_dir / "source").mkdir(parents=True)
        (work_dir / "source" / "dataset.zip").write_bytes(b"fake zip")
        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.TF_ZIP,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=work_dir / "source" / "dataset.zip",
            work_dir=work_dir,
            source_format=api_module.SourceFormat.TF_ZIP,
            name="Summa Theologiae 1200 ENG",
            description="",
            job_id="j",
        )
        assert result.name == "summa-theologiae-1200-eng.corpus"

    def test_empty_name_falls_back_to_job_id(self, tmp_path, monkeypatch, manager):
        """When the display name has no alphanumeric content, the on-disk
        filename falls back to the job id. Uses TF_ZIP with a
        punctuation-only filename so `_clean_filename_stem` returns "" and
        `_slugify(display_name)` is empty -> job_id fallback in
        `_resolve_corpus_path`."""
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-empty"
        (work_dir / "source").mkdir(parents=True)
        # A filename whose stem is all dashes -> cleaned to empty.
        (work_dir / "source" / "---.zip").write_bytes(b"fake zip")
        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.TF_ZIP,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=work_dir / "source" / "---.zip",
            work_dir=work_dir,
            source_format=api_module.SourceFormat.TF_ZIP,
            name="",
            description="",
            job_id="fixed-id",
        )
        assert result.name == "fixed-id.corpus"

    def test_collision_appends_short_suffix(self, tmp_path, monkeypatch, manager):
        """Two jobs with the same display name keep unique on-disk files."""
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        (tmp_path / "results").mkdir(parents=True)
        # Pre-existing file at the slug-derived path simulates a sibling job
        # that already finished -- the new call must not overwrite it.
        (tmp_path / "results" / "my-doc.corpus").write_bytes(b"prior")

        work_dir = tmp_path / "work" / "job-collide"
        (work_dir / "source").mkdir(parents=True)
        (work_dir / "source" / "dataset.zip").write_bytes(b"fake zip")
        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.TF_ZIP,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=work_dir / "source" / "dataset.zip",
            work_dir=work_dir,
            source_format=api_module.SourceFormat.TF_ZIP,
            name="My Doc",
            description="",
            job_id="j",
        )
        assert result.name.startswith("my-doc-")
        assert result.name.endswith(".corpus")
        assert result.name != "my-doc.corpus"
        # The prior file is untouched.
        assert (tmp_path / "results" / "my-doc.corpus").read_bytes() == b"prior"


class TestCleanFilenameStem:
    def test_replaces_dashes_with_spaces(self):
        assert (
            api_module._clean_filename_stem("summa-theologia-1200-ENG.xml")
            == "summa theologia 1200 ENG"
        )

    def test_replaces_underscores_with_spaces(self):
        assert api_module._clean_filename_stem("on_the_incarnation.txt") == "on the incarnation"

    def test_strips_extension(self):
        assert api_module._clean_filename_stem("document.pdf") == "document"

    def test_collapses_repeated_whitespace(self):
        assert api_module._clean_filename_stem("a--b__c.xml") == "a b c"

    def test_strips_leading_and_trailing_whitespace(self):
        assert api_module._clean_filename_stem("  hello  ") == "hello"

    def test_preserves_letter_case(self):
        assert api_module._clean_filename_stem("MyBook.epub") == "MyBook"


class TestExtractSourceTitle:
    def test_returns_none_for_tf_zip(self, tmp_path):
        # TF_ZIP has no parser -- no source metadata to extract.
        source = tmp_path / "dataset.zip"
        source.write_bytes(b"fake zip")
        assert (
            api_module._extract_source_title(
                api_module.SourceFormat.TF_ZIP, source
            )
            is None
        )

    def test_returns_none_for_tei_zip(self, tmp_path):
        # TEI_ZIP is not in PARSERS (multi-document; no single title).
        source = tmp_path / "tei.zip"
        source.write_bytes(b"fake zip")
        assert (
            api_module._extract_source_title(
                api_module.SourceFormat.TEI_ZIP, source
            )
            is None
        )

    def test_returns_title_from_plain_text_parser(self, tmp_path):
        # PlainTextParser derives a title from the filename stem.
        source = tmp_path / "my-document.txt"
        source.write_text("hello world\n\nsecond paragraph")
        title = api_module._extract_source_title(
            api_module.SourceFormat.PLAIN, source
        )
        assert title == "my-document"

    def test_returns_title_from_html_parser(self, tmp_path):
        source = tmp_path / "page.html"
        source.write_text(
            "<html><head><title>On the Incarnation</title></head>"
            "<body><p>text</p></body></html>"
        )
        title = api_module._extract_source_title(
            api_module.SourceFormat.HTML, source
        )
        assert title == "On the Incarnation"

    def test_returns_title_from_tei_parser(self, tmp_path):
        source = tmp_path / "summa.tei"
        source.write_text(
            "<TEI><teiHeader><fileDesc><titleStmt>"
            "<title>Summa Theologiae</title>"
            "</titleStmt></fileDesc></teiHeader><body><p>text</p></body></TEI>"
        )
        title = api_module._extract_source_title(
            api_module.SourceFormat.TEI, source
        )
        assert title == "Summa Theologiae"

    def test_parse_failure_returns_none(self, tmp_path, monkeypatch):
        # A corrupt source that raises during parse_metadata should not
        # crash the conversion -- _extract_source_title catches and logs,
        # returning None so the caller falls back to the request name.
        source = tmp_path / "broken.tei"
        source.write_text("not valid xml at all <<<<")
        result = api_module._extract_source_title(
            api_module.SourceFormat.TEI, source
        )
        assert result is None


class TestDeriveDisplayName:
    def test_source_title_wins_over_request_name(self, tmp_path, monkeypatch):
        source = tmp_path / "summa-theologia-1200-ENG.tei"
        source.write_text(
            "<TEI><teiHeader><fileDesc><titleStmt>"
            "<title>Summa Theologiae</title>"
            "</titleStmt></fileDesc></teiHeader><body><p>text</p></body></TEI>"
        )
        name = api_module._derive_display_name(
            source_format=api_module.SourceFormat.TEI,
            source_path=source,
            name="summa-theologia-1200-ENG",
        )
        assert name == "Summa Theologiae"

    def test_request_name_used_when_no_source_title(self, tmp_path):
        # A plain-text file's parser-derived title is the filename stem; if
        # the request `name` is more descriptive, it should NOT win -- the
        # source title (from the parser) has priority. But for TF_ZIP
        # (no parser), the request name is the fallback.
        source = tmp_path / "dataset.zip"
        source.write_bytes(b"fake zip")
        name = api_module._derive_display_name(
            source_format=api_module.SourceFormat.TF_ZIP,
            source_path=source,
            name="My Custom Name",
        )
        assert name == "My Custom Name"

    def test_cleaned_filename_stem_when_no_title_and_no_name(self, tmp_path):
        source = tmp_path / "summa-theologia-1200-ENG.xml"
        source.write_text("<root/>")
        # XML has no converter (no PARSERS entry for the converter), but
        # XmlParser IS in PARSERS -- it would try to parse. Use TF_ZIP
        # instead to guarantee no source title.
        source = tmp_path / "summa-theologia-1200-ENG.zip"
        source.write_bytes(b"fake zip")
        name = api_module._derive_display_name(
            source_format=api_module.SourceFormat.TF_ZIP,
            source_path=source,
            name="",
        )
        assert name == "summa theologia 1200 ENG"

    def test_whitespace_only_source_title_falls_back(self, tmp_path, monkeypatch):
        # A source title that is only whitespace should not be used.
        source = tmp_path / "doc.tei"
        source.write_text(
            "<TEI><teiHeader><fileDesc><titleStmt>"
            "<title>   </title>"
            "</titleStmt></fileDesc></teiHeader><body><p>text</p></body></TEI>"
        )
        name = api_module._derive_display_name(
            source_format=api_module.SourceFormat.TEI,
            source_path=source,
            name="Fallback Name",
        )
        assert name == "Fallback Name"


class TestRunConversionDisplayName:
    def test_display_name_set_on_job_from_source_title(
        self, tmp_path, monkeypatch, manager
    ):
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-title"
        (work_dir / "source").mkdir(parents=True)
        source = work_dir / "source" / "summa.tei"
        source.write_text(
            "<TEI><teiHeader><fileDesc><titleStmt>"
            "<title>Summa Theologiae</title>"
            "</titleStmt></fileDesc></teiHeader><body><p>text</p></body></TEI>"
        )

        captured_name = {}

        def fake_convert_to_corpus(tf_dir, corpus_path, **kw):
            captured_name["name"] = kw.get("name")
            return Path(corpus_path)

        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.TEI,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module, "convert_to_corpus", fake_convert_to_corpus
        )
        # Submit a deferred job so `set_display_name` has a job to update
        # -- _run_conversion is called directly (not via the executor), but
        # it still calls job_manager.set_display_name(job_id, ...).
        manager.submit(
            source_format=api_module.SourceFormat.TEI,
            name="upload-filename-stem",
            fn=lambda: Path("x"),
            job_id="j-title",
        )
        api_module._run_conversion(
            source_path=source,
            work_dir=work_dir,
            source_format=api_module.SourceFormat.TEI,
            name="upload-filename-stem",
            description="",
            job_id="j-title",
        )
        # The source title wins over the request name.
        assert captured_name["name"] == "Summa Theologiae"
        # And it was set on the job.
        job = manager.get("j-title")
        assert job.display_name == "Summa Theologiae"

    def test_display_name_falls_back_to_request_name_for_tf_zip(
        self, tmp_path, monkeypatch, manager
    ):
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-zip"
        (work_dir / "source").mkdir(parents=True)
        source = work_dir / "source" / "dataset.zip"
        source.write_bytes(b"fake zip")

        captured_name = {}

        def fake_convert_to_corpus(tf_dir, corpus_path, **kw):
            captured_name["name"] = kw.get("name")
            return Path(corpus_path)

        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.TF_ZIP,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module, "convert_to_corpus", fake_convert_to_corpus
        )
        manager.submit(
            source_format=api_module.SourceFormat.TF_ZIP,
            name="My Dataset",
            fn=lambda: Path("x"),
            job_id="j-zip",
        )
        api_module._run_conversion(
            source_path=source,
            work_dir=work_dir,
            source_format=api_module.SourceFormat.TF_ZIP,
            name="My Dataset",
            description="",
            job_id="j-zip",
        )
        assert captured_name["name"] == "My Dataset"
        assert manager.get("j-zip").display_name == "My Dataset"

    def test_archive_filename_slugified_from_display_name(
        self, tmp_path, monkeypatch, manager
    ):
        """The on-disk `.corpus` filename is the slug of the display name
        (the source title), not the request name (the upload filename
        stem) -- so `Summa Theologiae` -> `summa-theologiae.corpus`, not
        `summa-theologia-1200-eng.corpus` (issue #109)."""
        monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
        work_dir = tmp_path / "work" / "job-slug-title"
        (work_dir / "source").mkdir(parents=True)
        source = work_dir / "source" / "summa-theologia-1200-ENG.tei"
        source.write_text(
            "<TEI><teiHeader><fileDesc><titleStmt>"
            "<title>Summa Theologiae</title>"
            "</titleStmt></fileDesc></teiHeader><body><p>text</p></body></TEI>"
        )
        monkeypatch.setitem(
            api_module.CONVERTERS,
            api_module.SourceFormat.TEI,
            lambda src, out: Path(out),
        )
        monkeypatch.setattr(
            api_module,
            "convert_to_corpus",
            lambda tf_dir, corpus_path, **kw: Path(corpus_path),
        )
        result = api_module._run_conversion(
            source_path=source,
            work_dir=work_dir,
            source_format=api_module.SourceFormat.TEI,
            name="summa-theologia-1200-ENG",
            description="",
            job_id="j",
        )
        assert result.name == "summa-theologiae.corpus"
