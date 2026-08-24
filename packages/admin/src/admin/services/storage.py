"""Hugging Face Hub storage for converted `.corpus` archives.

`convert_to_corpus()` leaves finished archives on local disk
(`_RESULTS_ROOT`, see `api.py`), which only the machine that ran the
conversion can see. This module pushes those archives to a single Hugging
Face Hub location (`HF_STORAGE_REPO`, a Xet-backed **bucket** by default) so
the Corpora and Exegia apps can fetch a corpus from anywhere, and gives the
desktop app a durable library that survives the sidecar's temp-dir lifetime.

`HF_STORAGE_REPO_TYPE` selects the backing Hub primitive. A converted corpus
is an opaque `.corpus` archive rather than a browsable dataset, so the
default is `"bucket"` -- Hugging Face bucket object storage (addressed as
`hf://buckets/<owner>/<name>/...`), not a dataset repo. Classic repo types
(`"model"`/`"dataset"`/`"space"`) still work; `CorpusStorage` routes each
operation to the matching `huggingface_hub` API for the configured type
(`create_bucket`/`batch_bucket_files`/`list_bucket_tree`/... for buckets,
`create_repo`/`upload_file`/`list_repo_tree`/... for repos), and presents the
same `StoredCorpus` surface either way so `storage_api.py`/`storage_mcp.py`
never have to care which backend is in use.

Everything here is synchronous -- `huggingface_hub`'s `HfApi` is a plain
requests-based client -- so async surfaces (the `/storage` router in
`storage_api.py`, the MCP tools in `storage_mcp.py`) must call through
`asyncio.to_thread`, the same rule `validation_api.py` follows for
text-fabric.

Configuration comes from `common.utils.config.Settings` (`HF_STORAGE_REPO`,
`HF_TOKEN`, ...). An unconfigured location is a per-call
`StorageNotConfiguredError`, not an import-time failure: the combined app
must keep serving `/convert` even when Hub storage was never set up.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from common.utils.config import settings
from huggingface_hub import HfApi
from huggingface_hub.errors import (
    BucketNotFoundError,
    EntryNotFoundError,
    HfHubHTTPError,
    RepositoryNotFoundError,
)

logger = logging.getLogger(__name__)

_CORPUS_SUFFIX = ".corpus"


class StorageError(Exception):
    """Base error for Hub storage operations (network, auth, bad input)."""


class StorageNotConfiguredError(StorageError):
    """Raised when `HF_STORAGE_REPO` is unset -- storage was never enabled."""


class CorpusNotFoundError(StorageError):
    """Raised when the named archive does not exist in the storage repo."""


class ReadOnlyStorageError(StorageError):
    """Raised when a write is attempted while `HF_READ_ONLY` is set.

    The authoritative guard: every Hub write funnels through
    `CorpusStorage.upload`/`.delete` (manifest/annotation PATCHes re-upload via
    `_republish`), so refusing here blocks all write paths -- HTTP, MCP, and any
    future caller -- by construction. HTTP surfaces map it to 403.
    """


@dataclass(frozen=True)
class StoredCorpus:
    """One `.corpus` archive as it exists in the Hub storage repo."""

    filename: str
    size_bytes: int | None
    repo_id: str
    url: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _safe_archive_name(raw: str) -> str:
    """Normalize a caller-supplied name to a flat `<name>.corpus` filename.

    Strips any path segments (`../x`, `a/b.corpus`) the same way `api.py`'s
    `_save_upload` does for uploads -- the storage repo is a flat namespace
    and a filename must never escape it or address another repo path.
    """
    name = Path(raw).name
    if name in ("", ".", ".."):
        raise StorageError(f"Invalid corpus filename: {raw!r}")
    if not name.endswith(_CORPUS_SUFFIX):
        name += _CORPUS_SUFFIX
    return name


class CorpusStorage:
    """List, inspect, upload, download, and delete `.corpus` archives on the Hub.

    A thin, deliberately stateless wrapper over `huggingface_hub.HfApi`: no
    caching, no background threads, one Hub location. Constructed once at
    module import (`corpus_storage` below) with values from `Settings`; tests
    build their own instance with an injected fake `api`.

    The location is either a **bucket** (`repo_type == "bucket"`, the default
    -- Xet object storage addressed as `hf://buckets/<repo_id>/...`) or a
    classic repo (`"model"`/`"dataset"`/`"space"`). Each public method routes
    to the bucket API (`create_bucket`, `batch_bucket_files`,
    `list_bucket_tree`, `get_bucket_paths_info`, `download_bucket_files`) or
    the repo API (`create_repo`, `upload_file`, `list_repo_tree`,
    `get_paths_info`, `hf_hub_download`, `delete_file`) accordingly, and
    returns the same `StoredCorpus` either way.
    """

    # Hub archives are shared/global, not per-user: the corpus-detail cache
    # (`corpus_detail._cache_key`) may key extractions by plain filename. The
    # Supabase backend overrides this -- see `storage_supabase`.
    scopes_by_owner = False

    def __init__(
        self,
        repo_id: str | None = None,
        repo_type: str | None = None,
        token: str | None = None,
        api: HfApi | None = None,
    ) -> None:
        self.repo_id = repo_id if repo_id is not None else settings.hf_storage_repo
        self.repo_type = repo_type or settings.hf_storage_repo_type
        self._api = api or HfApi(token=token or settings.hf_token)

    @property
    def _is_bucket(self) -> bool:
        return self.repo_type == "bucket"

    def _require_repo(self) -> str:
        if not self.repo_id:
            raise StorageNotConfiguredError(
                "Hub storage is not configured: set HF_STORAGE_REPO "
                "(e.g. 'user/corpora-archives') and HF_TOKEN."
            )
        return self.repo_id

    def _url_for(self, filename: str) -> str:
        # Buckets resolve at hf://buckets/<owner>/<name>/<path> ->
        # https://huggingface.co/buckets/<owner>/<name>/resolve/<path> (no
        # branch segment); classic repos keep the type-prefixed /resolve/main/.
        if self._is_bucket:
            return f"https://huggingface.co/buckets/{self.repo_id}/resolve/{filename}"
        prefix = "" if self.repo_type == "model" else f"{self.repo_type}s/"
        return f"https://huggingface.co/{prefix}{self.repo_id}/resolve/main/{filename}"

    def ensure_repo(self) -> None:
        """Create the storage location if it doesn't exist yet (idempotent)."""
        if self._is_bucket:
            self._api.create_bucket(
                self._require_repo(),
                private=settings.hf_storage_private,
                exist_ok=True,
            )
            return
        self._api.create_repo(
            self._require_repo(),
            repo_type=self.repo_type,
            private=settings.hf_storage_private,
            exist_ok=True,
        )

    def list(self) -> list[StoredCorpus]:
        """All `.corpus` archives here. Empty if the location doesn't exist yet."""
        repo_id = self._require_repo()
        try:
            entries: Iterable[Any]
            if self._is_bucket:
                entries = self._api.list_bucket_tree(repo_id, recursive=True)
            else:
                entries = self._api.list_repo_tree(
                    repo_id, repo_type=self.repo_type, recursive=True
                )
            return [
                StoredCorpus(
                    filename=entry.path,
                    size_bytes=getattr(entry, "size", None),
                    repo_id=repo_id,
                    url=self._url_for(entry.path),
                )
                for entry in entries
                if entry.path.endswith(_CORPUS_SUFFIX)
            ]
        except (RepositoryNotFoundError, BucketNotFoundError):
            # Nothing has been uploaded yet (ensure_repo() runs on first
            # upload) -- an empty library, not an error.
            return []
        except HfHubHTTPError as exc:
            raise StorageError(f"Could not list corpora in {repo_id}: {exc}") from exc

    def info(self, filename: str) -> StoredCorpus:
        """Metadata for one archive; raises `CorpusNotFoundError` if absent."""
        repo_id = self._require_repo()
        filename = _safe_archive_name(filename)
        try:
            paths: list[Any]
            if self._is_bucket:
                paths = list(self._api.get_bucket_paths_info(repo_id, paths=[filename]))
            else:
                paths = list(
                    self._api.get_paths_info(
                        repo_id, paths=[filename], repo_type=self.repo_type
                    )
                )
        except (RepositoryNotFoundError, BucketNotFoundError) as exc:
            raise CorpusNotFoundError(
                f"Storage location {repo_id} does not exist yet"
            ) from exc
        except HfHubHTTPError as exc:
            raise StorageError(f"Could not read {filename} in {repo_id}: {exc}") from exc
        if not paths:
            raise CorpusNotFoundError(f"No corpus named {filename!r} in {repo_id}")
        entry = paths[0]
        return StoredCorpus(
            filename=entry.path,
            size_bytes=getattr(entry, "size", None),
            repo_id=repo_id,
            url=self._url_for(entry.path),
        )

    def upload(self, local_path: Path | str, filename: str | None = None) -> StoredCorpus:
        """Push a local `.corpus` archive to the Hub, creating the location if needed."""
        if settings.hf_read_only:
            raise ReadOnlyStorageError("Hub storage is read-only; uploads are disabled.")
        local = Path(local_path).expanduser()
        if not local.is_file():
            raise StorageError(f"Not a corpus archive file: {local}")
        name = _safe_archive_name(filename or local.name)
        repo_id = self._require_repo()
        self.ensure_repo()
        try:
            if self._is_bucket:
                self._api.batch_bucket_files(repo_id, add=[(str(local), name)])
            else:
                self._api.upload_file(
                    path_or_fileobj=str(local),
                    path_in_repo=name,
                    repo_id=repo_id,
                    repo_type=self.repo_type,
                    commit_message=f"Upload {name}",
                )
        except HfHubHTTPError as exc:
            raise StorageError(f"Could not upload {name} to {repo_id}: {exc}") from exc
        logger.info("Uploaded corpus %s to %s", name, repo_id)
        return self.info(name)

    def download(self, filename: str, dest_dir: Path | str) -> Path:
        """Fetch one archive into `dest_dir`, returning the local file path."""
        repo_id = self._require_repo()
        filename = _safe_archive_name(filename)
        try:
            if self._is_bucket:
                # download_bucket_files takes (remote, local-destination) pairs
                # and returns None, so build the destination path ourselves.
                dest = Path(dest_dir) / filename
                dest.parent.mkdir(parents=True, exist_ok=True)
                self._api.download_bucket_files(
                    repo_id,
                    files=[(filename, str(dest))],
                    raise_on_missing_files=True,
                )
                local: str | Path = dest
            else:
                local = self._api.hf_hub_download(
                    repo_id,
                    filename,
                    repo_type=self.repo_type,
                    local_dir=str(dest_dir),
                )
        except (EntryNotFoundError, RepositoryNotFoundError, BucketNotFoundError) as exc:
            raise CorpusNotFoundError(
                f"No corpus named {filename!r} in {repo_id}"
            ) from exc
        except HfHubHTTPError as exc:
            raise StorageError(
                f"Could not download {filename} from {repo_id}: {exc}"
            ) from exc
        return Path(local)

    def delete(self, filename: str) -> None:
        """Remove one archive from the location; raises `CorpusNotFoundError` if absent."""
        if settings.hf_read_only:
            raise ReadOnlyStorageError("Hub storage is read-only; deletes are disabled.")
        repo_id = self._require_repo()
        filename = _safe_archive_name(filename)
        try:
            if self._is_bucket:
                # Bucket batch-delete doesn't surface a missing member as an
                # error, so preserve the repo path's "missing -> not found"
                # contract by confirming existence first (raises
                # CorpusNotFoundError when absent).
                self.info(filename)
                self._api.batch_bucket_files(repo_id, delete=[filename])
            else:
                self._api.delete_file(
                    filename,
                    repo_id,
                    repo_type=self.repo_type,
                    commit_message=f"Delete {filename}",
                )
        except (EntryNotFoundError, RepositoryNotFoundError, BucketNotFoundError) as exc:
            raise CorpusNotFoundError(
                f"No corpus named {filename!r} in {repo_id}"
            ) from exc
        except HfHubHTTPError as exc:
            raise StorageError(
                f"Could not delete {filename} from {repo_id}: {exc}"
            ) from exc
        logger.info("Deleted corpus %s from %s", filename, repo_id)


def make_corpus_storage() -> CorpusStorage:
    """Build the storage backend selected by `STORAGE_BACKEND` (issue #110 C).

    Both backends expose the identical public surface
    (`list`/`info`/`upload`/`download`/`delete`/`ensure_repo` -> `StoredCorpus`
    plus the errors above), so the REST routes, MCP tools, and corpus-detail
    layer are backend-agnostic by construction. The Supabase import is lazy so
    a Hub-only deployment never touches that module.
    """
    if settings.storage_backend == "supabase":
        from .storage_supabase import SupabaseCorpusStorage

        return SupabaseCorpusStorage()  # type: ignore[return-value]
    return CorpusStorage()


# Module-level singleton, same pattern as `job_manager` (`jobs.py`): the
# router and the MCP tools must share one instance so tests can swap it in
# a single place.
corpus_storage = make_corpus_storage()
