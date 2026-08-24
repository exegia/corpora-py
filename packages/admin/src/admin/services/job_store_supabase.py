"""Supabase-backed `JobStore` + `ResultStore` (issue #140).

The in-process `MemoryJobStore` + local `_RESULTS_ROOT` cannot survive a
Vercel instance recycle: a poll can 404 mid-job, and job-scoped detail
(`GET /convert/{id}/index|content|nodes|versions`) 404s as soon as the
converting instance is gone. This module is the shared backend:

- **Metadata** (`SupabaseJobStore`) — one row per job in Postgres via
  PostgREST (`/rest/v1/{table}`), service-role key. Same 4-method
  `JobStore` surface `JobManager` already fronts.
- **Result bytes** (`SupabaseResultStore`) — the finished `.corpus` /
  `.graph.json` under the `conversion-jobs/` prefix in a Storage bucket,
  so a different instance can materialize the archive locally and serve
  detail without Hub filename matching.

Selected by `JOB_STORE=supabase`. Independent of `STORAGE_BACKEND`: Hub
can stay the publish-only surface (`huggingface`, `HF_READ_ONLY`) while
jobs still persist. `HF_READ_ONLY` does **not** apply here — these writes
are not Hub publishing.

Talks to PostgREST and Storage REST directly with `requests` (already a
`huggingface_hub` dependency), matching `storage_supabase.py`. Everything
is blocking; `JobManager` already runs on worker threads.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from common.utils.config import settings

from ..parsers.schema import SourceFormat
from .jobs import (
    ConversionJob,
    JobStatus,
    JobStore,
    JobStoreError,
    JobStoreNotConfiguredError,
    ResultStore,
    SnapshotMissingError,
    snapshot_key_for,
)

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30
_BLOB_TIMEOUT_SECONDS = 120
_LIST_LIMIT = 1000
_RESULT_PREFIX = "conversion-jobs"
_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
# Storage API answers 400 ("Object not found") about as often as 404.
_NOT_FOUND_STATUSES = (400, 404)


def _safe_table(name: str) -> str:
    if not _TABLE_NAME.match(name):
        raise JobStoreError("Invalid jobs table name")
    return name


def _safe_job_id(job_id: str) -> str:
    if not job_id or "/" in job_id or ".." in job_id or "\\" in job_id:
        raise JobStoreError("Invalid job id")
    return job_id


def _source_format_to_row(source_format: SourceFormat | str) -> str:
    if isinstance(source_format, SourceFormat):
        return source_format.value
    return str(source_format)


def _source_format_from_row(value: str) -> SourceFormat | str:
    try:
        return SourceFormat(value)
    except ValueError:
        return value


def job_to_row(job: ConversionJob) -> dict[str, Any]:
    """Serialize a job for PostgREST. Local `result_path` is not stored."""
    return {
        "id": job.id,
        "source_format": _source_format_to_row(job.source_format),
        "name": job.name,
        "status": job.status.value,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result_key": job.result_key,
        "error": job.error,
        "logs": list(job.logs),
        "owner": job.owner,
        "display_name": job.display_name,
    }


def job_from_row(row: dict[str, Any]) -> ConversionJob:
    """Deserialize a PostgREST row. `result_path` stays unset until materialize."""
    logs = row.get("logs") or []
    if isinstance(logs, str):
        logs = json.loads(logs)
    status_raw = row.get("status") or JobStatus.QUEUED
    return ConversionJob(
        id=row["id"],
        source_format=_source_format_from_row(row["source_format"]),
        name=row.get("name") or "",
        status=JobStatus(status_raw),
        created_at=float(row["created_at"]),
        started_at=None if row.get("started_at") is None else float(row["started_at"]),
        finished_at=None
        if row.get("finished_at") is None
        else float(row["finished_at"]),
        result_path=None,
        result_key=row.get("result_key"),
        error=row.get("error"),
        logs=list(logs),
        owner=row.get("owner"),
        display_name=row.get("display_name"),
    )


class SupabaseJobStore(JobStore):
    """Postgres-backed job metadata via PostgREST (service-role key)."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        table: str | None = None,
        session: Any = None,
    ) -> None:
        self.url = (url or settings.supabase_api_url or "").rstrip("/")
        self._key = key or settings.supabase_service_role_key
        self.table = _safe_table(table or settings.supabase_jobs_table)
        self._session = session or requests.Session()

    def _require_configured(self) -> None:
        if not (self.url and self._key and self.table):
            raise JobStoreNotConfiguredError(
                "Job store is not configured: set JOB_STORE=supabase, "
                "SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_URL (or PROJECT_REF)."
            )

    def _headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._key}",
            "apikey": self._key or "",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _table_url(self) -> str:
        return f"{self.url}/rest/v1/{self.table}"

    def _request(self, method: str, *, params: dict[str, str], **kwargs: Any) -> Any:
        self._require_configured()
        try:
            resp = self._session.request(
                method,
                self._table_url(),
                params=params,
                headers=kwargs.pop("headers", self._headers()),
                timeout=_TIMEOUT_SECONDS,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise JobStoreError("Job store request failed") from exc
        if resp.status_code >= 400:
            raise JobStoreError(
                f"Job store returned {resp.status_code}"
            )
        if not resp.content:
            return []
        try:
            return resp.json()
        except ValueError as exc:
            raise JobStoreError("Job store returned invalid JSON") from exc

    def get(self, job_id: str) -> ConversionJob | None:
        rows = self._request(
            "GET",
            params={"id": f"eq.{_safe_job_id(job_id)}", "select": "*"},
            headers=self._headers(),
        )
        if not rows:
            return None
        return job_from_row(rows[0])

    def put(self, job: ConversionJob) -> None:
        self._request(
            "POST",
            params={"on_conflict": "id"},
            headers=self._headers(prefer="resolution=merge-duplicates,return=minimal"),
            json=job_to_row(job),
        )

    def list(self, *, owner: str | None) -> list[ConversionJob]:
        params = {"select": "*", "limit": str(_LIST_LIMIT)}
        if owner is not None:
            params["owner"] = f"eq.{owner}"
        rows = self._request("GET", params=params, headers=self._headers())
        return [job_from_row(row) for row in rows]

    def delete(self, job_id: str) -> ConversionJob | None:
        rows = self._request(
            "DELETE",
            params={"id": f"eq.{_safe_job_id(job_id)}"},
            headers=self._headers(prefer="return=representation"),
        )
        if not rows:
            return None
        return job_from_row(rows[0])


class SupabaseResultStore(ResultStore):
    """Object-storage backend for conversion result archives.

    Paths are ``conversion-jobs/{job_id}{suffix}`` so they never collide
    with a library listing of ``{sub}/{filename}`` on the same bucket
    (`STORAGE_BACKEND=supabase`). Access control is job visibility, not
    the object path.
    """

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        bucket: str | None = None,
        session: Any = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.url = (url or settings.supabase_api_url or "").rstrip("/")
        self._key = key or settings.supabase_service_role_key
        self.bucket = (
            bucket
            if bucket is not None
            else (settings.supabase_jobs_bucket or settings.supabase_storage_bucket)
        )
        self._session = session or requests.Session()
        self._cache_dir = cache_dir or (
            Path(tempfile.gettempdir()) / "corpora-admin-results"
        )
        self._bucket_ensured = False

    def _require_configured(self) -> str:
        if not (self.url and self._key and self.bucket):
            raise JobStoreNotConfiguredError(
                "Job result store is not configured: set JOB_STORE=supabase, "
                "SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL (or PROJECT_REF), "
                "and SUPABASE_JOBS_BUCKET or SUPABASE_STORAGE_BUCKET."
            )
        return self.bucket

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "apikey": self._key or ""}

    def _object_url(self, path: str) -> str:
        quoted = "/".join(quote(seg, safe="") for seg in path.split("/"))
        return f"{self.url}/storage/v1/object/{self.bucket}/{quoted}"

    def _key_for(self, job_id: str, path: Path) -> str:
        suffix = path.suffix if path.suffix else ".corpus"
        if path.name.endswith(".graph.json"):
            suffix = ".graph.json"
        elif path.suffix == ".corpus" or path.name.endswith(".corpus"):
            suffix = ".corpus"
        return f"{_RESULT_PREFIX}/{_safe_job_id(job_id)}{suffix}"

    def _ensure_bucket(self) -> None:
        if self._bucket_ensured:
            return
        bucket = self._require_configured()
        try:
            resp = self._session.post(
                f"{self.url}/storage/v1/bucket",
                json={"id": bucket, "name": bucket, "public": False},
                headers=self._headers(),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise JobStoreError("Job result store request failed") from exc
        if resp.status_code in (200, 201):
            self._bucket_ensured = True
            return
        if resp.status_code in (400, 409) and "exist" in resp.text.lower():
            self._bucket_ensured = True
            return
        raise JobStoreError(f"Could not create result bucket ({resp.status_code})")

    def save(self, job_id: str, path: Path) -> str | None:
        bucket = self._require_configured()
        local = Path(path).expanduser()
        if not local.is_file():
            raise JobStoreError("Conversion result file is missing")
        self._ensure_bucket()
        key = self._key_for(job_id, local)
        content_type = (
            "application/json"
            if key.endswith(".json")
            else "application/zip"
        )
        try:
            with local.open("rb") as fh:
                # PUT + x-upsert overwrites HEAD (POST to an existing object
                # 400s on Storage even with x-upsert — snapshots already PUT).
                resp = self._session.put(
                    self._object_url(key),
                    data=fh,
                    headers={
                        **self._headers(),
                        "x-upsert": "true",
                        "Content-Type": content_type,
                    },
                    timeout=_BLOB_TIMEOUT_SECONDS,
                )
        except requests.RequestException as extra:
            raise JobStoreError("Job result upload failed") from extra
        if resp.status_code not in (200, 201):
            raise JobStoreError(
                f"Could not upload conversion result ({resp.status_code})"
            )
        logger.info("Uploaded conversion result %s to bucket %s", key, bucket)
        return key

    def save_snapshot(self, job_id: str, path: Path, label: str) -> str | None:
        """PUT ``conversion-jobs/{job_id}/{label}.corpus``. Never fails the job.

        A missed snapshot is logged and returns ``None`` so the conversion
        can still succeed (issue #147). Extra labels are for #149.
        """
        key = snapshot_key_for(job_id, label)
        if key is None:
            logger.warning(
                "Snapshot skipped for job %s: invalid label %r", job_id, label
            )
            return None
        try:
            bucket = self._require_configured()
            local = Path(path).expanduser()
            if not local.is_file():
                logger.warning(
                    "Snapshot skipped for job %s: result file is missing", job_id
                )
                return None
            self._ensure_bucket()
            with local.open("rb") as fh:
                resp = self._session.put(
                    self._object_url(key),
                    data=fh,
                    headers={
                        **self._headers(),
                        "x-upsert": "true",
                        "Content-Type": "application/zip",
                    },
                    timeout=_BLOB_TIMEOUT_SECONDS,
                )
        except (JobStoreError, requests.RequestException, OSError):
            logger.warning(
                "Snapshot upload failed for job %s", job_id, exc_info=True
            )
            return None
        if resp.status_code not in (200, 201):
            logger.warning(
                "Could not upload snapshot %s (%s); conversion still succeeded",
                key,
                resp.status_code,
            )
            return None
        logger.info("Uploaded conversion snapshot %s to bucket %s", key, bucket)
        return key

    def materialize(self, key: str, job_id: str) -> Path:
        self._require_configured()
        if not key.startswith(f"{_RESULT_PREFIX}/") or ".." in key:
            raise JobStoreError("Invalid result key")
        try:
            resp = self._session.get(
                self._object_url(key),
                headers=self._headers(),
                timeout=_BLOB_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise JobStoreError("Job result download failed") from exc
        if resp.status_code in _NOT_FOUND_STATUSES:
            if key.count("/") >= 2:
                raise SnapshotMissingError("Snapshot is no longer available")
            raise JobStoreError("Conversion result is no longer available")
        if resp.status_code != 200:
            raise JobStoreError(
                f"Could not download conversion result ({resp.status_code})"
            )
        dest = self._cache_dir / Path(key).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(resp.content)
        tmp.replace(dest)
        return dest

    def delete(self, key: str) -> None:
        if not key:
            return
        self._require_configured()
        try:
            resp = self._session.delete(
                self._object_url(key),
                headers=self._headers(),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise JobStoreError("Job result delete failed") from exc
        if resp.status_code in _NOT_FOUND_STATUSES:
            return
        if resp.status_code != 200:
            raise JobStoreError(
                f"Could not delete conversion result ({resp.status_code})"
            )
