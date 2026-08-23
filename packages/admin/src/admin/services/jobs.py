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
response is sent. Job state lives in an in-memory registry so multiple
clients (a polling REST client, a WebSocket) can observe the same job.

See `packages/admin/CLAUDE.md` and `services/websocket.py` for why this
reports coarse status (queued/running/succeeded/failed) rather than a
percentage: the conversion pipeline has no progress hook.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

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


class JobQueueFullError(Exception):
    """Raised by `JobManager.submit` when too many jobs are queued/running.

    Deliberately a plain exception, not an `HTTPException` -- this module
    has no FastAPI dependency (see `JobManager`'s docstring); callers in
    `api.py` translate it to a 429.
    """


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

    def to_dict(self) -> dict[str, Any]:
        # The on-disk `result_path.name` (e.g. `job-abc123.corpus`) is a
        # server-internal unique id, not a useful library filename. The
        # `result_filename` we expose is derived from the user-supplied
        # `name` and always ends in `.corpus` for /convert jobs -- so a
        # client that stores only this field never persists the original
        # source file as the library object (see issue #108). When
        # `result_path` is set we still prefer its name, since a collision-
        # aware `_run_conversion` may have appended a uniqueness suffix to
        # the on-disk file that the client must echo back on download.
        if self.result_path is not None:
            result_filename = self.result_path.name
        else:
            result_filename = result_filename_for(
                self.name, self.source_format, job_id=self.id
            )
        return {
            "id": self.id,
            "source_format": self.source_format.value
            if isinstance(self.source_format, SourceFormat)
            else self.source_format,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "logs": list(self.logs),
            "last_log": self.logs[-1] if self.logs else None,
            "result_filename": result_filename,
            "download_ready": self.status == JobStatus.SUCCEEDED
            and self.result_path is not None,
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

    A process-local singleton is enough here: conversion output lands on
     the local disk (see `convert_to_corpus`), so a multi-worker/multi-process
    deployment would need a shared store and queue (Redis, Celery, ...) instead
    of this in-memory registry. That's a deliberate scope cut for a
    single-process admin/conversion service, not an oversight -- revisit if
    this ever needs to run behind more than one uvicorn worker. See
    `corpora_py.app`'s `main()` for the corresponding "stay single-process"
    guard on the server side.

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
    """

    def __init__(
        self,
        max_workers: int = 2,
        *,
        max_pending: int = 50,
        stall_timeout_seconds: float = 15 * 60,
    ) -> None:
        self._jobs: dict[str, ConversionJob] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="convert"
        )
        self._max_pending = max_pending
        self._stall_timeout_seconds = stall_timeout_seconds

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
            pending = sum(
                1 for j in self._jobs.values() if j.status not in _TERMINAL_STATUSES
            )
            if pending >= self._max_pending:
                raise JobQueueFullError(
                    f"{pending} conversions already queued/running (limit {self._max_pending})"
                )
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, fn)
        return job

    def _run(self, job: ConversionJob, fn: Callable[[], Path]) -> None:
        with self._lock:
            job.status = JobStatus.RUNNING
            job.started_at = time.time()
        try:
            result_path = fn()
            error = None
        except Exception as exc:
            # Full detail server-side only -- `job.error` round-trips to
            # HTTP/WebSocket clients via `to_dict()` and must not leak
            # internal paths (work_dir, tempfile.gettempdir(), ...) or
            # library internals.
            logger.exception("Conversion job %s failed", job.id)
            result_path = None
            error = f"Conversion failed: {type(exc).__name__} (job id {job.id})"

        with self._lock:
            if job.status in _TERMINAL_STATUSES:
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
                    job.status.value,
                )
                return
            job.result_path = result_path
            job.error = error
            job.status = JobStatus.FAILED if error else JobStatus.SUCCEEDED
            job.finished_at = time.time()

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
        would mean the job was somehow evicted mid-run, which nothing does
        today, but this shouldn't be able to crash a worker thread either way.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.logs.append(message)
            del job.logs[:-_MAX_LOG_LINES]

    def get(self, job_id: str) -> ConversionJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._check_stall(job)
            return job

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


# Process-wide singleton, mirroring `corpus_manager` in `corpora_mcp.corpus`.
job_manager = JobManager()
