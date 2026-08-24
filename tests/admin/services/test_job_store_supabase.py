"""Tests for `admin.services.job_store_supabase`.

Every test injects a `FakeSession` -- no network, no key leaves the process.
Covers row round-trip, upsert/list/delete, result upload/materialize, and
the unconfigured 503-style errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from admin.parsers.schema import SourceFormat
from admin.services.job_store_supabase import (
    SupabaseJobStore,
    SupabaseResultStore,
    job_from_row,
    job_to_row,
)
from admin.services.jobs import (
    ConversionJob,
    JobStatus,
    JobStoreError,
    JobStoreNotConfiguredError,
)

URL = "https://proj.supabase.co"
KEY = "service-role-key"
TABLE = "conversion_jobs"
BUCKET = "conversion-jobs"


def _job(**kwargs) -> ConversionJob:
    defaults = {
        "id": "j1",
        "source_format": SourceFormat.PLAIN,
        "name": "doc",
        "status": JobStatus.QUEUED,
        "created_at": 1.0,
        "owner": "alice",
    }
    return ConversionJob(**{**defaults, **kwargs})


class FakeSession:
    """Stateful PostgREST + Storage stand-in shared by two store instances."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple] = []
        self.bucket_exists = False
        self.fail_status: int | None = None

    def request(self, method, url, **kwargs):
        method = method.upper()
        self.calls.append((method, url, kwargs))
        if self.fail_status is not None:
            return SimpleNamespace(
                status_code=self.fail_status, content=b"", text="nope", json=lambda: []
            )
        params = kwargs.get("params") or {}
        if method == "GET":
            if "id" in params and params["id"].startswith("eq."):
                job_id = params["id"][3:]
                row = self.rows.get(job_id)
                body = [row] if row else []
            else:
                body = list(self.rows.values())
                owner = params.get("owner")
                if owner and owner.startswith("eq."):
                    wanted = owner[3:]
                    body = [r for r in body if r.get("owner") == wanted]
            payload = json.dumps(body).encode()
            return SimpleNamespace(
                status_code=200,
                content=payload,
                text=payload.decode(),
                json=lambda: body,
            )
        if method == "POST":
            row = kwargs.get("json") or {}
            self.rows[row["id"]] = row
            return SimpleNamespace(
                status_code=201, content=b"", text="", json=lambda: []
            )
        if method == "DELETE":
            job_id = (params.get("id") or "")[3:]
            row = self.rows.pop(job_id, None)
            body = [row] if row else []
            payload = json.dumps(body).encode()
            return SimpleNamespace(
                status_code=200,
                content=payload,
                text=payload.decode(),
                json=lambda: body,
            )
        raise AssertionError(f"unexpected {method} {url}")

    def _put_object(self, url, **kwargs):
        if self.fail_status is not None:
            return SimpleNamespace(
                status_code=self.fail_status, content=b"", text="nope"
            )
        marker = f"/storage/v1/object/{BUCKET}/"
        path = url.split(marker, 1)[-1]
        data = kwargs.get("data")
        raw = data.read() if hasattr(data, "read") else data
        self.objects[path] = raw if isinstance(raw, bytes) else raw or b""
        return SimpleNamespace(status_code=200, content=b"", text="")

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if self.fail_status is not None:
            return SimpleNamespace(
                status_code=self.fail_status, content=b"", text="nope"
            )
        if url.endswith("/storage/v1/bucket"):
            self.bucket_exists = True
            return SimpleNamespace(status_code=200, content=b"", text="")
        return self._put_object(url, **kwargs)

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self._put_object(url, **kwargs)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        marker = f"/storage/v1/object/{BUCKET}/"
        path = url.split(marker, 1)[-1]
        if path not in self.objects:
            return SimpleNamespace(status_code=404, content=b"", text="missing")
        return SimpleNamespace(
            status_code=200, content=self.objects[path], text=""
        )

    def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, kwargs))
        marker = f"/storage/v1/object/{BUCKET}/"
        path = url.split(marker, 1)[-1]
        if path not in self.objects:
            return SimpleNamespace(status_code=404, content=b"", text="missing")
        del self.objects[path]
        return SimpleNamespace(status_code=200, content=b"", text="")


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def store(session) -> SupabaseJobStore:
    return SupabaseJobStore(url=URL, key=KEY, table=TABLE, session=session)


@pytest.fixture
def results(session, tmp_path) -> SupabaseResultStore:
    return SupabaseResultStore(
        url=URL, key=KEY, bucket=BUCKET, session=session, cache_dir=tmp_path / "cache"
    )


class TestRowRoundTrip:
    def test_preserves_fields(self):
        job = _job(
            status=JobStatus.SUCCEEDED,
            started_at=2.0,
            finished_at=3.0,
            result_key="conversion-jobs/j1.corpus",
            result_path=Path("/tmp/local.corpus"),
            error=None,
            logs=["a", "b"],
            display_name="Summa",
        )
        restored = job_from_row(job_to_row(job))
        assert restored.id == job.id
        assert restored.source_format == SourceFormat.PLAIN
        assert restored.status == JobStatus.SUCCEEDED
        assert restored.result_key == job.result_key
        assert restored.result_path is None  # local path is instance-specific
        assert restored.logs == ["a", "b"]
        assert restored.display_name == "Summa"
        assert restored.owner == "alice"

    def test_ingest_source_format_stays_a_string(self):
        job = _job(source_format="docx")
        restored = job_from_row(job_to_row(job))
        assert restored.source_format == "docx"


class TestSupabaseJobStore:
    def test_put_get_round_trip(self, store):
        store.put(_job(logs=["hi"], display_name="Title"))
        fetched = store.get("j1")
        assert fetched is not None
        assert fetched.display_name == "Title"
        assert fetched.logs == ["hi"]
        assert fetched.result_path is None

    def test_get_unknown_is_none(self, store):
        assert store.get("missing") is None

    def test_list_filters_by_owner(self, store):
        store.put(_job(id="a", owner="alice"))
        store.put(_job(id="b", owner="bob"))
        assert {j.id for j in store.list(owner="alice")} == {"a"}
        assert {j.id for j in store.list(owner=None)} == {"a", "b"}

    def test_delete_returns_row(self, store):
        store.put(_job())
        deleted = store.delete("j1")
        assert deleted is not None and deleted.id == "j1"
        assert store.get("j1") is None
        assert store.delete("j1") is None

    def test_put_is_upsert(self, store):
        store.put(_job(status=JobStatus.QUEUED))
        store.put(_job(status=JobStatus.RUNNING, started_at=5.0))
        assert store.get("j1").status == JobStatus.RUNNING
        assert store.get("j1").started_at == 5.0

    def test_two_stores_share_session_state(self, session):
        a = SupabaseJobStore(url=URL, key=KEY, table=TABLE, session=session)
        b = SupabaseJobStore(url=URL, key=KEY, table=TABLE, session=session)
        a.put(_job(status=JobStatus.SUCCEEDED, result_key="conversion-jobs/j1.corpus"))
        fetched = b.get("j1")
        assert fetched.status == JobStatus.SUCCEEDED
        assert fetched.result_key == "conversion-jobs/j1.corpus"

    def test_unconfigured_raises(self, session):
        store = SupabaseJobStore(url="", key=KEY, table=TABLE, session=session)
        with pytest.raises(JobStoreNotConfiguredError):
            store.get("j1")
        assert session.calls == []

    def test_http_error_is_job_store_error(self, store, session):
        session.fail_status = 500
        with pytest.raises(JobStoreError, match="500"):
            store.get("j1")

    def test_invalid_table_name_rejected(self, session):
        with pytest.raises(JobStoreError, match="table name"):
            SupabaseJobStore(
                url=URL, key=KEY, table="conversion-jobs;drop", session=session
            )


class TestSupabaseResultStore:
    def test_save_materialize_delete(self, results, session, tmp_path):
        src = tmp_path / "out.corpus"
        src.write_bytes(b"archive-bytes")
        key = results.save("j1", src)
        assert key == "conversion-jobs/j1.corpus"
        assert session.objects[key] == b"archive-bytes"
        dest = results.materialize(key, "j1")
        assert dest.read_bytes() == b"archive-bytes"
        results.delete(key)
        assert key not in session.objects

    def test_save_overwrites_existing_head_via_put(self, results, session, tmp_path):
        src = tmp_path / "out.corpus"
        src.write_bytes(b"first")
        key = results.save("j1", src)
        src.write_bytes(b"second")
        assert results.save("j1", src) == key
        assert session.objects[key] == b"second"
        put_urls = [url for method, url, _ in session.calls if method == "PUT"]
        assert any(url.endswith(f"{BUCKET}/{key}") or key in url for url in put_urls)

    def test_graph_json_suffix(self, results, tmp_path):
        src = tmp_path / "out.graph.json"
        src.write_bytes(b'{"ok":true}')
        key = results.save("j1", src)
        assert key == "conversion-jobs/j1.graph.json"

    def test_materialize_missing_raises(self, results):
        with pytest.raises(JobStoreError, match="no longer available"):
            results.materialize("conversion-jobs/missing.corpus", "missing")

    def test_delete_missing_is_noop(self, results):
        results.delete("conversion-jobs/missing.corpus")

    def test_unconfigured_raises(self, session, tmp_path):
        store = SupabaseResultStore(
            url=URL, key="", bucket=BUCKET, session=session, cache_dir=tmp_path
        )
        with pytest.raises(JobStoreNotConfiguredError):
            store.save("j1", tmp_path)

    def test_rejects_path_escape_key(self, results):
        with pytest.raises(JobStoreError, match="Invalid result key"):
            results.materialize("../secret", "j1")

    def test_save_snapshot_put_url(self, results, session, tmp_path):
        src = tmp_path / "out.corpus"
        src.write_bytes(b"archive-bytes")
        results.save("j1", src)
        key = results.save_snapshot("j1", src, "v1.0")
        assert key == "conversion-jobs/j1/v1.0.corpus"
        put_urls = [url for method, url, _ in session.calls if method == "PUT"]
        assert any("v1.0.corpus" in url for url in put_urls)
        assert session.objects[key] == b"archive-bytes"

    def test_save_snapshot_failure_returns_none(self, results, session, tmp_path):
        src = tmp_path / "out.corpus"
        src.write_bytes(b"archive-bytes")
        results.save("j1", src)
        session.fail_status = 500
        assert results.save_snapshot("j1", src, "v1.0") is None
