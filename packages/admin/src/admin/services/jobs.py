"""In-process job registry + worker pool for long-running document conversions.

Document conversion (parse -> Text-Fabric -> .cfm -> .corpus) is synchronous,
CPU/IO-bound code (text-fabric, lxml, pypdf) that can run for minutes on a
large source (a full Bible, a multi-hundred-page EPUB). It must never run
inline inside an ASGI request coroutine, or it blocks every other request on
that worker for the full duration.

This module runs each conversion in a dedicated `ThreadPoolExecutor`,
decoupled from any individual HTTP request/response cycle -- unlike
`fastapi.BackgroundTasks`, which is tied to the lifetime of the request that
spawned it and offers no way to observe, cancel, or query a task after the
response is sent. Job state lives in a pluggable `JobStore` (default:
in-memory) so multiple clients (a polling REST client, a WebSocket) can
observe the same job, and a serverless deployment can swap in a shared
backend (Postgres, Redis) so jobs survive instance recycling.

See `packages/admin/CLAUDE.md` and `services/websocket.py` for why this
reports coarse status (queued/running/succeeded/failed) rather than a
percentage: the conversion pipeline has no progress hook.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from common.utils.config import settings

from ..parsers.schema import SourceFormat

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


_TERMINAL_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED)

# Coarse stage logging only fires a handful of times per job (see
# `ConversionJob.logs`'s docstring) -- this cap is a defensive backstop, not
# a real limit anything is expected to hit.
_MAX_LOG_LINES = 50

# Suffix per pipeline: `/convert` jobs package a `.corpus` archive, `/ingest`
# jobs write a `graph.json`. `result_filename` (`to_dict` below) and the
# `Content-Disposition` filename on the download routes both end in this
# suffix, so a client never persists the original source filename as the
# library object (see issue #108).
_CORPUS_SUFFIX = ".corpus"
_GRAPH_SUFFIX = ".graph.json"

# One or more non-alphanumeric characters collapsed to a single dash. Used
# by `_slugify` to turn a free-form `name` ("Summa Theologiae 1200 ENG") into
# a flat, safe filename stem ("summa-theologiae-1200-eng").
_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Snapshot labels are version tags like ``v1.0`` / ``v1.1`` (issue #147 / #149).
# Only ``v`` + digits + dots are allowed in the object key / local filename.
_SNAPSHOT_LABEL = re.compile(r"^v[0-9.]+$")


def snapshot_label(label: str) -> str | None:
    """Return a safe snapshot stem, or ``None`` if ``label`` is unusable."""
    cleaned = (label or "").strip()
    if _SNAPSHOT_LABEL.fullmatch(cleaned):
        return cleaned
    return None


def snapshot_key_for(job_id: str, label: str) -> str | None:
    """Object key ``conversion-jobs/{job_id}/{label}.corpus``, or ``None``.

    Extra labels (v1.1, …) are for later mutation bumps (#149); convert
    snapshots use ``v1.0`` (#147). Rejects path-like job ids so a bad
    id cannot escape the prefix.
    """
    safe = snapshot_label(label)
    if not safe:
        return None
    if not job_id or "/" in job_id or ".." in job_id or "\\" in job_id:
        return None
    return f"conversion-jobs/{job_id}/{safe}.corpus"


def _slugify(name: str) -> str:
    """Reduce a free-form `name` to a flat, filename-safe slug.

    Lowercases, collapses every non-alphanumeric run to a single `-`, and
    strips leading/trailing dashes. Returns ``""`` for an empty/whitespace/
    punctuation-only input -- callers fall back to the job id in that case.
    """
    return _SLUG_NON_ALNUM.sub("-", (name or "").strip().lower()).strip("-")


def result_filename_for(
    name: str,
    source_format: SourceFormat | str,
    *,
    job_id: str = "",
) -> str:
    """The human-readable filename a client should store the result under.

    Always ends in ``.corpus`` for `/convert` jobs (a `SourceFormat`) and
    ``.graph.json`` for `/ingest` jobs (a bare detected-suffix string). The
    stem is `_slugify(name)`; falls back to the job id when `name` is empty
    or has no alphanumeric content. This is what `to_dict()` exposes as
    `result_filename` and what the download routes set as
    `Content-Disposition` -- so a client that stores only this filename
    never persists the original source file as the library object.
    """
    slug = _slugify(name) or _slugify(job_id) or job_id
    if isinstance(source_format, SourceFormat):
        return f"{slug}{_CORPUS_SUFFIX}"
    return f"{slug}{_GRAPH_SUFFIX}"


class JobFailedError(Exception):
    """A job failure whose message is safe to expose in ``job.error``.

    `JobManager._run` normally replaces exception text with a generic
    message (internal paths, library internals must not round-trip to
    clients). Raise this — with a deliberately client-facing message —
    when the failure reason *is* the product surface, e.g. a converted
    corpus failing post-conversion validation (issue #177).
    """


class JobQueueFullError(Exception):
    """Raised by `JobManager.submit` when too many jobs are queued/running.

    Deliberately a plain exception, not an `HTTPException` -- this module
    has no FastAPI dependency (see `JobManager`'s docstring); callers in
    `api.py` translate it to a 429.
    """


class JobStoreError(Exception):
    """Raised when the job store or result store cannot complete an operation.

    Callers in `api.py` / `ingest_api.py` translate this to HTTP 503. The
    message may be operator-facing (misconfiguration) but must not leak
    internal URLs or keys.
    """


class JobStoreNotConfiguredError(JobStoreError):
    """Raised when `JOB_STORE=supabase` but URL/key/table/bucket are unset."""


class SnapshotMissingError(JobStoreError):
    """The labeled snapshot is not in the result store (issue #148)."""


# ── Pluggable job store ───────────────────────────────────────────────────────


class JobStore(ABC):
    """Storage backend for `JobManager`.

    The default `MemoryJobStore` is a dict held in-process; a serverless
    deployment (Vercel, multiple uvicorn workers) can swap in a Postgres or
    Redis-backed implementation so jobs survive instance recycling and are
    visible cross-process. `JobManager` holds the lock and coordinates all
    access, so implementations do **not** need their own locking.
    """

    @abstractmethod
    def get(self, job_id: str) -> ConversionJob | None:
        """Return the job for ``job_id``, or ``None`` if unknown."""

    @abstractmethod
    def put(self, job: ConversionJob) -> None:
        """Insert or update ``job`` (keyed by ``job.id``)."""

    @abstractmethod
    def list(self, *, owner: str | None) -> list[ConversionJob]:
        """Return all jobs, filtered by ``owner`` when not ``None``.

        When ``owner`` is ``None`` (auth disabled / anonymous deployment),
        return every job in the store.
        """

    @abstractmethod
    def delete(self, job_id: str) -> ConversionJob | None:
        """Remove and return the job for ``job_id``, or ``None`` if unknown."""


class ResultStore(ABC):
    """Blob store for a job's result file (``.corpus`` / ``.graph.json``).

    Metadata in `JobStore` is not enough for job-scoped detail: `/index`
    has to read the archive bytes. The default `LocalResultStore` is a
    no-op (the converting instance already has `result_path` on disk). A
    serverless deployment injects a shared backend so a different instance
    can materialize those bytes after the converter is gone (issue #140).

    ``save_snapshot`` stores a labeled copy of HEAD (``v1.0`` on convert,
    later ``v1.1`` … on mutation bumps — issue #147 / #149) under a
    distinct key so restore (#148) can fetch it without rewriting HEAD.
    """

    @abstractmethod
    def save(self, job_id: str, path: Path) -> str | None:
        """Persist ``path`` and return a store key, or ``None`` if local-only."""

    @abstractmethod
    def save_snapshot(self, job_id: str, path: Path, label: str) -> str | None:
        """Persist a labeled HEAD snapshot and return its key, or ``None``.

        Must not raise on failure — a missed snapshot must not fail the
        conversion job (issue #147). Extra ``label`` values are reserved
        for later mutation bumps (#149).
        """

    @abstractmethod
    def materialize(self, key: str, job_id: str) -> Path:
        """Fetch ``key`` into a local cache file and return that path."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a previously saved result. Missing keys are a no-op."""


class LocalResultStore(ResultStore):
    """Default: results live only at the converting instance's `result_path`.

    ``save`` is still a no-op (the converting instance already has the
    file). ``save_snapshot`` copies bytes next to ``cache_dir`` (or next
    to the source file) so tests and local restores can find v1.0.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir
        self._snapshots: dict[str, Path] = {}

    def save(self, job_id: str, path: Path) -> str | None:
        return None

    def save_snapshot(self, job_id: str, path: Path, label: str) -> str | None:
        key = snapshot_key_for(job_id, label)
        if key is None:
            return None
        src = Path(path)
        if not src.is_file():
            logger.warning(
                "Local snapshot skipped for job %s: result file is missing", job_id
            )
            return None
        dest_dir = self._cache_dir if self._cache_dir is not None else src.parent
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{job_id}-{snapshot_label(label)}.corpus"
            if dest.resolve() != src.resolve():
                shutil.copy2(src, dest)
        except OSError:
            logger.warning(
                "Local snapshot copy failed for job %s", job_id, exc_info=True
            )
            return None
        self._snapshots[key] = dest
        return key

    def materialize(self, key: str, job_id: str) -> Path:
        path = self._snapshots.get(key)
        if path is not None and path.is_file():
            return path
        parts = key.replace("\\", "/").split("/")
        if len(parts) == 3 and parts[0] == "conversion-jobs":
            label = snapshot_label(Path(parts[2]).stem)
            dest_dir = self._cache_dir
            if label and dest_dir is not None:
                dest = dest_dir / f"{job_id}-{label}.corpus"
                if dest.is_file():
                    return dest
            raise SnapshotMissingError("Snapshot is no longer available")
        raise JobStoreError("Local result store has no remote keys to materialize")

    def delete(self, key: str) -> None:
        return None


class MemoryJobStore(JobStore):
    """Default in-process store: a plain dict (no locking — the caller owns that)."""

    def __init__(self) -> None:
        self._jobs: dict[str, ConversionJob] = {}

    def get(self, job_id: str) -> ConversionJob | None:
        return self._jobs.get(job_id)

    def put(self, job: ConversionJob) -> None:
        self._jobs[job.id] = job

    def list(self, *, owner: str | None) -> list[ConversionJob]:
        if owner is None:
            return list(self._jobs.values())
        return [j for j in self._jobs.values() if j.owner == owner]

    def delete(self, job_id: str) -> ConversionJob | None:
        return self._jobs.pop(job_id, None)


@dataclass
class ConversionJob:
    id: str
    # A `SourceFormat` for /convert jobs; a bare string (the detected file
    # suffix, e.g. "docx") for /ingest jobs, whose Docling pipeline accepts
    # formats the parser enum doesn't enumerate.
    source_format: SourceFormat | str
    name: str
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result_path: Path | None = None
    # Remote key for the result bytes (issue #140), e.g.
    # ``conversion-jobs/{id}.corpus``. `None` on the in-memory/local store.
    # Not exposed via `to_dict()` -- callers hydrate a local `result_path`
    # through `JobManager.materialize` before serving download/detail.
    result_key: str | None = None
    error: str | None = None
    # Coarse, human-readable stage markers (e.g. "Parsing source...",
    # "Building .corpus archive...") appended by `JobManager.log()` from
    # `_run_conversion` (see `api.py`). Not real per-unit progress -- the
    # conversion pipeline has no progress hook (see this module's own
    # docstring) -- just enough for a client to show *something* moving
    # besides a stalled-looking progress bar. Capped at `_MAX_LOG_LINES`.
    logs: list[str] = field(default_factory=list)
    # The submitter's JWT `sub` claim (see `corpora_py.auth.AuthMiddleware`),
    # or `None` if the job was created while auth was disabled. Not exposed
    # via `to_dict()` -- it's only used by `is_visible_to()` for access
    # control, not client-facing data.
    owner: str | None = None
    # The human-readable title written to `manifest.name`, derived from the
    # source document's own metadata (TEI `titleStmt`, PDF `info.title`, HTML
    # `<title>`, EPUB `dc:title`) when available, falling back to the request
    # `name` and then to a cleaned upload filename stem (see issue #109).
    # `None` until the worker thread extracts it in `_run_conversion`; set via
    # `JobManager.set_display_name` so it appears on the running/succeeded
    # status without re-parsing the archive. The slug-based `result_filename`
    # is derived from this once set, so the on-disk archive name follows the
    # human title, not the upload filename.
    display_name: str | None = None
    # Post-conversion validation summary (issue #177):
    # `corpora_mcp.validate.validate_corpus_archive(...).summary()` — keys
    # `corpus` / `valid` / `stats` / `reasons` / `checks`. `None` until the
    # worker runs validation (and for /ingest jobs, which have no archive).
    # Set via `JobManager.set_validation` so it appears on the terminal
    # status; an invalid archive also fails the job with the top reasons in
    # `error` (see `_run_conversion` in `api.py`).
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        # The on-disk `result_path.name` (e.g. `job-abc123.corpus`) is a
        # server-internal unique id, not a useful library filename. The
        # `result_filename` we expose is derived from the display name (or
        # the request `name` before the title is known) and always ends in
        # `.corpus` for /convert jobs -- so a client that stores only this
        # field never persists the original source file as the library
        # object (see issues #108/#109). When `result_path` is set we still
        # prefer its name, since a collision-aware `_run_conversion` may
        # have appended a uniqueness suffix to the on-disk file that the
        # client must echo back on download.
        if self.result_path is not None:
            result_filename = self.result_path.name
        else:
            result_filename = result_filename_for(
                self.display_name or self.name,
                self.source_format,
                job_id=self.id,
            )
        return {
            "id": self.id,
            "source_format": self.source_format.value
            if isinstance(self.source_format, SourceFormat)
            else self.source_format,
            "name": self.name,
            "display_name": self.display_name,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "logs": list(self.logs),
            "last_log": self.logs[-1] if self.logs else None,
            "validation": self.validation,
            "result_filename": result_filename,
            "download_ready": self.status == JobStatus.SUCCEEDED
            and (self.result_path is not None or bool(self.result_key)),
        }

    def is_visible_to(self, claims: dict[str, Any] | None) -> bool:
        """Whether a request carrying `claims` may poll/download this job.

        `claims` is whatever `AuthMiddleware` put in `scope["state"]["user"]`
        (`None` if auth is currently disabled, or the request somehow reached
        this far without it -- `AuthMiddleware` normally rejects that case
        with 401 before it gets here).

        Permissive on either side of the comparison lacking an identity: a
        job created with no owner (auth was off when it was submitted) is
        visible to everyone, and a request with no claims (auth is currently
        off) can see any job. Only an owner-vs-claims *mismatch* is denied.
        This intentionally doesn't retroactively lock down jobs submitted
        before auth was turned on, or lock everyone out if auth is turned
        back off later -- ownership is enforced only when there's identity
        on both sides to compare.
        """
        if self.owner is None or claims is None:
            return True
        return claims.get("sub") == self.owner


class JobManager:
    """Tracks conversion jobs and runs them on a background thread pool.

    A pluggable `JobStore` (default: in-memory) holds job state. For a
    single-process deployment the default `MemoryJobStore` is sufficient;
    a serverless / multi-worker deployment can inject a shared backend
    (Postgres, Redis) so jobs survive instance recycling and are visible
    cross-process.

    `max_pending` is a blunt, in-memory-only backpressure stopgap (reject new
    submissions once too many jobs are queued/running), not real
    queueing/backpressure -- there's still no limit on how long a job can sit
    queued once accepted, and the cap resets on process restart.

    `stall_timeout_seconds` is a *soft* watchdog, not a hard timeout: a
    `ThreadPoolExecutor` cannot forcibly stop a thread that's already
    running, so a job stuck past this threshold gets marked `FAILED` (so
    clients stop waiting on it) but its worker thread keeps running the
    stuck call underneath -- the thread is not reclaimed. Repeated timeouts
    can still exhaust the pool. A real fix needs process-isolated execution
    (subprocess / `ProcessPoolExecutor`, which in turn needs `submit()` to
    take a picklable job spec instead of an arbitrary closure) -- out of
    scope here, tracked in `packages/admin/CLAUDE.md`'s "Known gaps".

    `retention_seconds` (0 = disabled) controls lazy TTL reaping: terminal
    jobs older than this are removed from the store and their result files
    deleted on the next `list_jobs` or `submit` call, bounding disk and
    memory usage for long-running processes.

    `results` is the blob store for finished archives. The default
    `LocalResultStore` does nothing; a shared `JobStore` deployment must
    inject a backend that both *saves* bytes on success and *materializes*
    them on another instance (issue #140). Metadata without bytes still
    404s job-scoped detail after recycle.
    """

    def __init__(
        self,
        max_workers: int = 2,
        *,
        max_pending: int = 50,
        stall_timeout_seconds: float = 15 * 60,
        retention_seconds: float = 0,
        store: JobStore | None = None,
        results: ResultStore | None = None,
    ) -> None:
        self._store = store or MemoryJobStore()
        self._results = results or LocalResultStore()
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="convert"
        )
        self._max_pending = max_pending
        self._stall_timeout_seconds = stall_timeout_seconds
        self._retention_seconds = retention_seconds

    def submit(
        self,
        *,
        source_format: SourceFormat | str,
        name: str,
        fn: Callable[[], Path],
        owner: str | None = None,
        job_id: str | None = None,
    ) -> ConversionJob:
        """Register a new job and hand `fn` to the worker pool.

        `fn` must be a zero-argument callable that does the actual blocking
        conversion work and returns the path to the finished `.corpus` file
        (or raises on failure). Raises `JobQueueFullError` without touching `fn`
        if too many jobs are already queued/running.

        `owner` should be the submitter's JWT `sub` claim (or `None` if auth
        is disabled) -- see `ConversionJob.is_visible_to()`.

        `job_id`, if given, is used as the job's id instead of minting a new
        one. This lets a caller (see `api.py`'s `create_conversion`) know the
        id *before* `fn` runs, so `fn` can call `job_manager.log(job_id, ...)`
        from inside the worker thread -- referencing the `ConversionJob`
        object returned by this call from within `fn`'s closure would be a
        race, since the executor can start running `fn` before this method
        returns it.
        """
        job = ConversionJob(
            id=job_id or str(uuid.uuid4()),
            source_format=source_format,
            name=name,
            owner=owner,
        )
        with self._lock:
            self._reap_expired()
            pending = sum(
                1 for j in self._store.list(owner=None) if j.status not in _TERMINAL_STATUSES
            )
            if pending >= self._max_pending:
                raise JobQueueFullError(
                    f"{pending} conversions already queued/running (limit {self._max_pending})"
                )
            self._store.put(job)
        self._executor.submit(self._run, job, fn)
        return job

    def _run(self, job: ConversionJob, fn: Callable[[], Path]) -> None:
        with self._lock:
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
            self._store.put(job)
        try:
            result_path = fn()
            result_key = None
            if result_path is not None:
                # Upload *before* marking succeeded so another instance
                # that reads the terminal row can materialize the bytes.
                result_key = self._results.save(job.id, Path(result_path))
                # v1.0 HEAD snapshot (issue #147). Failure here must not
                # flip the job to FAILED — restore can fall back to HEAD
                # while it is still v1.0. Extra labels are for #149.
                if Path(result_path).name.endswith(".corpus"):
                    try:
                        self._results.save_snapshot(
                            job.id, Path(result_path), "v1.0"
                        )
                    except Exception:
                        logger.warning(
                            "Conversion job %s snapshot save failed; job still succeeded",
                            job.id,
                            exc_info=True,
                        )
            error = None
        except Exception as exc:
            # Full detail server-side only -- `job.error` round-trips to
            # HTTP/WebSocket clients via `to_dict()` and must not leak
            # internal paths (work_dir, tempfile.gettempdir(), ...) or
            # library internals.
            logger.exception("Conversion job %s failed", job.id)
            result_path = None
            result_key = None
            if isinstance(exc, JobFailedError) and str(exc):
                error = str(exc)
            else:
                error = f"Conversion failed: {type(exc).__name__} (job id {job.id})"

        with self._lock:
            # Re-read: `log` / `set_display_name` / a stall check on another
            # instance may have put a newer copy while `fn()` ran. Putting
            # this method's original object would clobber those fields (and
            # a shared store returns a deserialized copy, not this object).
            current = self._store.get(job.id)
            if current is None:
                logger.warning(
                    "Conversion job %s finished but is no longer in the store; dropping result",
                    job.id,
                )
                return
            if current.status in _TERMINAL_STATUSES:
                # `_check_stall` (called from `get()`, under this same lock)
                # already marked this job FAILED for exceeding
                # `stall_timeout_seconds` while `fn()` was still running.
                # Don't clobber that verdict -- without this check, a job
                # that stalls and then eventually finishes would silently
                # flip back to SUCCEEDED/a fresh FAILED, contradicting
                # whatever a client already observed (and already
                # disconnected over, in the WebSocket case) when it stalled.
                #
                # If `fn()` did succeed here, `result_path` points at a real
                # `.corpus` file in `_RESULTS_ROOT` that's now orphaned --
                # this job will never report it (status stays FAILED), so it
                # won't be cleaned up by anything that keys off job state
                # either. Logged at warning level so an operator can find
                # and manually reap it; not auto-recovered, since there's no
                # client left to hand a late "actually it succeeded" to in
                # the common case (the WebSocket already closed on FAILED).
                logger.warning(
                    "Conversion job %s finished (result_path=%s, error=%s) after already "
                    "being marked %s by the stall watchdog; keeping the watchdog's verdict "
                    "-- any produced result_path above is now an orphaned file",
                    job.id,
                    result_path,
                    error,
                    current.status.value,
                )
                return
            current.result_path = result_path
            current.result_key = result_key
            current.error = error
            current.status = JobStatus.FAILED if error else JobStatus.SUCCEEDED
            current.finished_at = time.time()
            self._store.put(current)

    def _check_stall(self, job: ConversionJob) -> None:
        """Mark a job FAILED if it's been RUNNING past `stall_timeout_seconds`.

        Called under `self._lock` from `get()` -- the only place this runs.
        There is no background timer: a stalled job whose id nobody ever
        polls/downloads again stays reported as RUNNING forever, even though
        its worker thread is, per the class docstring, never reclaimed
        either way. This only affects the *reported* status, not whether the
        pool slot is stuck.
        """
        if (
            job.status == JobStatus.RUNNING
            and job.started_at is not None
            and time.time() - job.started_at > self._stall_timeout_seconds
        ):
            logger.warning(
                "Conversion job %s exceeded %.0fs stall timeout; marking failed "
                "(worker thread may still be running in the background)",
                job.id,
                self._stall_timeout_seconds,
            )
            job.error = f"Conversion timed out after {self._stall_timeout_seconds / 60:.0f} minutes"
            job.status = JobStatus.FAILED
            job.finished_at = time.time()

    def log(self, job_id: str, message: str) -> None:
        """Append a coarse stage message to a job's log, if it still exists.

        Called from a worker thread (see `_run_conversion` in `api.py`)
        while other threads may be reading `job.logs` via `get()`/`to_dict()`
        -- guarded by the same lock as every other mutation. Silently a
        no-op for an unknown `job_id` rather than raising: a job can only
        reach this codepath through `JobManager.submit()`, so a miss here
        would mean the job was somehow evicted mid-run (e.g. by TTL
        reaping), but this shouldn't be able to crash a worker thread either way.
        """
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return
            job.logs.append(message)
            del job.logs[:-_MAX_LOG_LINES]
            self._store.put(job)

    def set_display_name(self, job_id: str, display_name: str) -> None:
        """Set the human-readable title on a job, if it still exists.

        Called from a worker thread (see `_run_conversion` in `api.py`) once
        the source document's own title has been extracted, so the
        running/succeeded status exposes it without the client re-parsing the
        archive (see issue #109). Guarded by the same lock as every other
        mutation; silently a no-op for an unknown `job_id`, matching `log`.
        """
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return
            job.display_name = display_name
            self._store.put(job)

    def set_validation(self, job_id: str, summary: dict[str, Any]) -> None:
        """Attach a post-conversion validation summary to a job (issue #177).

        Called from a worker thread after `validate_corpus_archive` runs, so
        the summary rides the terminal status regardless of pass/fail. Same
        lock + no-op-on-unknown-id semantics as `log`/`set_display_name`.
        """
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return
            job.validation = summary
            self._store.put(job)

    def get(self, job_id: str) -> ConversionJob | None:
        with self._lock:
            job = self._store.get(job_id)
            if job is not None:
                before = job.status
                self._check_stall(job)
                if job.status != before:
                    # Persist the stall verdict so a shared store doesn't
                    # keep serving RUNNING to the next instance.
                    self._store.put(job)
            return job

    def materialize(self, job: ConversionJob) -> Path | None:
        """Ensure ``job.result_path`` is a readable local file.

        No-op when the converting instance still has the file. On a
        different instance, downloads via `result_key`. Returns ``None``
        when there is nothing to serve (queued/failed, or the blob is gone).
        Does not hold ``_lock`` across the download -- two concurrent
        materializations of the same job may both fetch, which is cheaper
        than blocking polls on a large archive.
        """
        if job.result_path is not None and Path(job.result_path).is_file():
            return Path(job.result_path)
        if not job.result_key:
            return None
        path = self._results.materialize(job.result_key, job.id)
        job.result_path = path
        return path

    def materialize_snapshot(self, job_id: str, key: str) -> Path:
        """Return a local path for a labeled snapshot, or raise ``SnapshotMissingError``."""
        if not key:
            raise SnapshotMissingError("Snapshot is no longer available")
        try:
            path = self._results.materialize(key, job_id)
        except SnapshotMissingError:
            raise
        except JobStoreError:
            path = None
        if path is not None and Path(path).is_file():
            return Path(path)
        job = self.get(job_id)
        label = snapshot_label(Path(key).stem)
        if job is not None and job.result_path is not None and label:
            sibling = Path(job.result_path).parent / f"{job_id}-{label}.corpus"
            if sibling.is_file():
                return sibling
        raise SnapshotMissingError("Snapshot is no longer available")

    def snapshot_file(self, job_id: str, path: Path, label: str) -> str | None:
        """Persist a labeled HEAD snapshot. Failure is logged, not raised.

        Extra labels (v1.1, …) are mutation bumps (issue #149); convert
        writes ``v1.0``. A missed snapshot must not fail the caller.
        """
        try:
            return self._results.save_snapshot(job_id, Path(path), label)
        except Exception:
            logger.warning(
                "Snapshot %s for job %s failed", label, job_id, exc_info=True
            )
            return None

    def replace_result(self, job_id: str, path: Path) -> str | None:
        """Overwrite the job's HEAD archive in the result store (issue #149)."""
        local = Path(path)
        if not local.is_file():
            raise JobStoreError(f"Replacement archive missing for job {job_id}")
        key = self._results.save(job_id, local)
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return key
            job.result_path = local
            if key:
                job.result_key = key
            self._store.put(job)
        return key

    def set_result_key(
        self, job_id: str, key: str, path: Path | None = None
    ) -> None:
        """Point the job's HEAD at ``key`` (a snapshot object after mutation).

        Storage does not reliably replace ``conversion-jobs/{id}.corpus``
        in place; unique snapshot keys do. After a 1.x bump, callers set
        ``result_key`` to the new snapshot so GET hydrates the new HEAD.
        """
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return
            job.result_key = key
            if path is not None:
                job.result_path = path
            self._store.put(job)

    def list_jobs(
        self,
        *,
        owner: str | None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ConversionJob], int]:
        """Return the caller's jobs (most recent first) with pagination.

        ``owner`` is the JWT ``sub`` claim (or ``None`` if auth is disabled).
        Reaps expired terminal jobs (see ``retention_seconds``) before listing
        so the count and disk usage stay bounded on a long-running process.
        Returns ``(jobs, total)`` where ``total`` is the full count before
        pagination.
        """
        with self._lock:
            self._reap_expired()
            jobs = self._store.list(owner=owner)
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            total = len(jobs)
            return jobs[offset : offset + limit], total

    def _reap_expired(self) -> None:
        """Remove terminal jobs older than ``retention_seconds`` and delete their result files.

        Called under ``self._lock`` from ``list_jobs`` and ``submit`` — lazy
        reaping, no background timer. ``retention_seconds <= 0`` disables it
        (the default). Keeps disk and memory bounded on a long-running
        process without a separate cleanup thread.
        """
        if self._retention_seconds <= 0:
            return
        now = time.time()
        for job in self._store.list(owner=None):
            if (
                job.status in _TERMINAL_STATUSES
                and job.finished_at is not None
                and now - job.finished_at > self._retention_seconds
            ):
                if job.result_key:
                    try:
                        self._results.delete(job.result_key)
                    except Exception:
                        logger.warning(
                            "Failed to delete result %s for expired job %s",
                            job.result_key,
                            job.id,
                            exc_info=True,
                        )
                for minor in range(33):
                    snap_key = snapshot_key_for(job.id, f"v1.{minor}")
                    if not snap_key:
                        continue
                    try:
                        self._results.delete(snap_key)
                    except Exception:
                        logger.warning(
                            "Failed to delete snapshot %s for expired job %s",
                            snap_key,
                            job.id,
                            exc_info=True,
                        )
                if job.result_path is not None:
                    Path(job.result_path).unlink(missing_ok=True)
                self._store.delete(job.id)
                logger.debug("Reaped expired job %s (finished %.0fs ago)", job.id, now - job.finished_at)

    def shutdown(self, *, wait: bool = False) -> None:
        """Best-effort shutdown for use from an app lifespan.

        `wait=False` (the default) is deliberate: a stalled job (see
        `_check_stall`) can occupy a worker thread indefinitely, and Python's
        `ThreadPoolExecutor` cannot forcibly kill a running thread regardless
        of `wait` -- `wait=True` would risk hanging process shutdown forever
        on exactly the failure mode this class already has to tolerate.
        `cancel_futures=True` still drops anything queued-but-not-yet-started.
        """
        self._executor.shutdown(wait=wait, cancel_futures=True)


def make_job_store() -> JobStore:
    """Build the job-metadata backend selected by `JOB_STORE` (issue #140).

    Lazy-imports the Supabase impl so a memory-only deployment never
    touches PostgREST. Tests inject a store directly onto `JobManager`.
    """
    if settings.job_store == "supabase":
        from .job_store_supabase import SupabaseJobStore

        return SupabaseJobStore()
    return MemoryJobStore()


def make_result_store() -> ResultStore:
    """Build the result-bytes backend to pair with `make_job_store()`."""
    if settings.job_store == "supabase":
        from .job_store_supabase import SupabaseResultStore

        return SupabaseResultStore()
    return LocalResultStore()


# Process-wide singleton, mirroring `corpus_manager` in `corpora_mcp.corpus`.
# Retention comes from JOB_RETENTION_SECONDS (0 = keep forever, the default).
# `JOB_STORE=supabase` swaps in a shared metadata + blob backend so poll and
# job-scoped detail survive instance recycle (issue #140).
job_manager = JobManager(
    retention_seconds=settings.job_retention_seconds,
    store=make_job_store(),
    results=make_result_store(),
)
