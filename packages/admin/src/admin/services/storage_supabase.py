"""Supabase Storage backend for converted `.corpus` archives (issue #110, option C).

The product library (each user's own converted corpora — what corpora-web
shows) lives in a private Supabase Storage bucket, not on the Hugging Face
Hub (see the "Library storage split" section in `services/CLAUDE.md`).
`SupabaseCorpusStorage` implements the exact same public surface as
`storage.CorpusStorage` (`list`/`info`/`upload`/`download`/`delete`/
`ensure_repo` → `StoredCorpus`), so with `STORAGE_BACKEND=supabase` the
`/storage` REST routes, the `storage_*` MCP tools, and the corpus-detail
layer all read the library bucket instead of the Hub — no call-site changes
(they share the `corpus_storage` singleton built by
`storage.make_corpus_storage()`).

**Owner scoping.** Object paths are ``{sub}/{filename}``, where ``sub`` is
the request's *verified* JWT claim taken from
`common.utils.request_context.current_owner` (set by the combined app's
`AuthMiddleware`). The service-role key bypasses the bucket's RLS, so this
prefix is the access control: a caller can only ever list or address objects
under their own ``sub``, and the prefix comes from the verified token, never
from client input. This matches the ``{user_id}/{job_id}.corpus`` layout
corpora-web writes, so library rows resolve directly. With no verified
identity (auth disabled — single-user local dev) paths are un-prefixed at
the bucket root.

Talks to the Storage REST API (``/storage/v1/...``) directly with `requests`
(already a `huggingface_hub` dependency) rather than pulling in the
`supabase-py` SDK — five endpoints don't justify a new dependency tree.
Everything here is blocking, same rule as `storage.py`: async surfaces call
through `asyncio.to_thread`.

`HF_READ_ONLY` is honored here too: it is the deployment-wide storage
read-only flag (see `Settings.hf_read_only`), not a Hub-only switch.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from common.utils.config import settings
from common.utils.request_context import current_owner

from .storage import (
    CorpusNotFoundError,
    ReadOnlyStorageError,
    StorageError,
    StorageNotConfiguredError,
    StoredCorpus,
    _safe_archive_name,
)

logger = logging.getLogger(__name__)

_CORPUS_SUFFIX = ".corpus"
_TIMEOUT_SECONDS = 30
# One list call fetches at most this many objects. A user's library is a few
# dozen corpora, not thousands; if that assumption ever breaks, page with the
# API's `offset` instead of raising this.
_LIST_LIMIT = 1000

# Statuses the Storage API uses for "no such object/bucket": it answers 400
# ("Object not found" / bucket errors) about as often as a plain 404.
_NOT_FOUND_STATUSES = (400, 404)


class SupabaseCorpusStorage:
    """List, inspect, upload, download, and delete `.corpus` objects in a bucket.

    Same deliberately stateless shape as `storage.CorpusStorage`: no caching,
    no background threads, one bucket, constructed once by
    `storage.make_corpus_storage()` with values from `Settings`; tests build
    their own instance with an injected fake `session`.
    """

    # Consulted by `corpus_detail._cache_key`: archives here are per-owner, so
    # the extraction cache must not share entries across owners.
    scopes_by_owner = True

    def __init__(
        self,
        bucket: str | None = None,
        url: str | None = None,
        key: str | None = None,
        session: Any = None,
    ) -> None:
        self.bucket = bucket if bucket is not None else settings.supabase_storage_bucket
        self.url = (url or settings.supabase_api_url or "").rstrip("/")
        self._key = key or settings.supabase_service_role_key
        self._session = session or requests.Session()

    # `StoredCorpus.repo_id` names the storage location; for this backend
    # that's the bucket.
    @property
    def repo_id(self) -> str | None:
        return self.bucket

    def _require_configured(self) -> str:
        if not (self.bucket and self.url and self._key):
            raise StorageNotConfiguredError(
                "Supabase storage is not configured: set SUPABASE_STORAGE_BUCKET, "
                "SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_URL (or PROJECT_REF)."
            )
        return self.bucket

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "apikey": self._key or ""}

    @staticmethod
    def _prefix() -> str:
        """The verified owner prefix for this request ("" when anonymous)."""
        return current_owner.get() or ""

    def _object_path(self, filename: str) -> str:
        name = _safe_archive_name(filename)
        prefix = self._prefix()
        return f"{prefix}/{name}" if prefix else name

    def _object_url(self, path: str) -> str:
        quoted = "/".join(quote(seg, safe="") for seg in path.split("/"))
        return f"{self.url}/storage/v1/object/{self.bucket}/{quoted}"

    def ensure_repo(self) -> None:
        """Create the bucket if it doesn't exist yet (idempotent, private)."""
        bucket = self._require_configured()
        resp = self._session.post(
            f"{self.url}/storage/v1/bucket",
            json={"id": bucket, "name": bucket, "public": False},
            headers=self._headers(),
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code in (200, 201):
            return
        # 400/409 with an "already exists" style message is the idempotent
        # success path; anything else is a real failure.
        if resp.status_code in (400, 409) and "exist" in resp.text.lower():
            return
        raise StorageError(
            f"Could not create bucket {bucket}: {resp.status_code} {resp.text}"
        )

    def list(self) -> list[StoredCorpus]:
        """The caller's `.corpus` objects. Empty if the bucket doesn't exist yet."""
        bucket = self._require_configured()
        resp = self._session.post(
            f"{self.url}/storage/v1/object/list/{bucket}",
            json={"prefix": self._prefix(), "limit": _LIST_LIMIT, "offset": 0},
            headers=self._headers(),
            timeout=_TIMEOUT_SECONDS,
        )
        if resp.status_code in _NOT_FOUND_STATUSES:
            # Nothing has been uploaded yet (ensure_repo() runs on first
            # upload) -- an empty library, not an error. Same contract as
            # CorpusStorage.list on a missing repo.
            return []
        if resp.status_code != 200:
            raise StorageError(
                f"Could not list corpora in {bucket}: {resp.status_code} {resp.text}"
            )
        prefix = self._prefix()
        stored = []
        for entry in resp.json():
            name = entry.get("name", "")
            # Folder placeholders come back with a null id; skip them along
            # with anything that isn't a .corpus object.
            if entry.get("id") is None or not name.endswith(_CORPUS_SUFFIX):
                continue
            path = f"{prefix}/{name}" if prefix else name
            metadata = entry.get("metadata") or {}
            stored.append(
                StoredCorpus(
                    filename=name,
                    size_bytes=metadata.get("size"),
                    repo_id=bucket,
                    url=self._object_url(path),
                )
            )
        return stored

    def info(self, filename: str) -> StoredCorpus:
        """Metadata for one object; raises `CorpusNotFoundError` if absent."""
        bucket = self._require_configured()
        name = _safe_archive_name(filename)
        for stored in self.list():
            if stored.filename == name:
                return stored
        raise CorpusNotFoundError(f"No corpus named {name!r} in {bucket}")

    def upload(self, local_path: Path | str, filename: str | None = None) -> StoredCorpus:
        """Push a local `.corpus` archive into the bucket under the owner prefix."""
        if settings.hf_read_only:
            raise ReadOnlyStorageError("Storage is read-only; uploads are disabled.")
        local = Path(local_path).expanduser()
        if not local.is_file():
            raise StorageError(f"Not a corpus archive file: {local}")
        bucket = self._require_configured()
        path = self._object_path(filename or local.name)
        self.ensure_repo()
        with local.open("rb") as fh:
            resp = self._session.post(
                self._object_url(path),
                data=fh,
                headers={
                    **self._headers(),
                    "x-upsert": "true",
                    "Content-Type": "application/zip",
                },
                timeout=_TIMEOUT_SECONDS,
            )
        if resp.status_code not in (200, 201):
            raise StorageError(
                f"Could not upload {path} to {bucket}: {resp.status_code} {resp.text}"
            )
        logger.info("Uploaded corpus %s to bucket %s", path, bucket)
        return self.info(Path(path).name)

    def download(self, filename: str, dest_dir: Path | str) -> Path:
        """Fetch one object into `dest_dir`, returning the local file path."""
        bucket = self._require_configured()
        name = _safe_archive_name(filename)
        path = self._object_path(name)
        resp = self._session.get(
            self._object_url(path), headers=self._headers(), timeout=_TIMEOUT_SECONDS
        )
        if resp.status_code in _NOT_FOUND_STATUSES:
            raise CorpusNotFoundError(f"No corpus named {name!r} in {bucket}")
        if resp.status_code != 200:
            raise StorageError(
                f"Could not download {path} from {bucket}: {resp.status_code} {resp.text}"
            )
        dest = Path(dest_dir) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    def delete(self, filename: str) -> None:
        """Remove one object from the bucket; raises `CorpusNotFoundError` if absent."""
        if settings.hf_read_only:
            raise ReadOnlyStorageError("Storage is read-only; deletes are disabled.")
        bucket = self._require_configured()
        name = _safe_archive_name(filename)
        path = self._object_path(name)
        resp = self._session.delete(
            self._object_url(path), headers=self._headers(), timeout=_TIMEOUT_SECONDS
        )
        if resp.status_code in _NOT_FOUND_STATUSES:
            raise CorpusNotFoundError(f"No corpus named {name!r} in {bucket}")
        if resp.status_code != 200:
            raise StorageError(
                f"Could not delete {path} from {bucket}: {resp.status_code} {resp.text}"
            )
        logger.info("Deleted corpus %s from bucket %s", path, bucket)
