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


class JobQueueFull(Exception):
    """Raised by `JobManager.submit` when too many jobs are queued/running.

    Deliberately a plain exception, not an `HTTPException` -- this module
    has no FastAPI dependency (see `JobManager`'s docstring); callers in
    `api.py` translate it to a 429.
    """


@dataclass
class ConversionJob:
    id: str
    source_format: SourceFormat
    name: str
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result_path: Path | None = None
    error: str | None = None
    # The submitter's JWT `sub` claim (see `corpora_py.auth.AuthMiddleware`),
    # or `None` if the job was created while auth was disabled. Not exposed
    # via `to_dict()` -- it's only used by `is_visible_to()` for access
    # control, not client-facing data.
    owner: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_format": self.source_format.value,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "download_ready": self.status == JobStatus.SUCCEEDED and self.result_path is not None,
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

    A process-local singleton is sufficient here: conversion output lands on
    local disk (see `convert_to_corpus`), so a multi-worker/multi-process
    deployment would need a shared store + queue (Redis, Celery, ...) instead
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
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="convert")
        self._max_pending = max_pending
        self._stall_timeout_seconds = stall_timeout_seconds

    def submit(
        self,
        *,
        source_format: SourceFormat,
        name: str,
        fn: Callable[[], Path],
        owner: str | None = None,
    ) -> ConversionJob:
        """Register a new job and hand `fn` to the worker pool.

        `fn` must be a zero-argument callable that does the actual blocking
        conversion work and returns the path to the finished `.corpus` file
        (or raises on failure). Raises `JobQueueFull` without touching `fn`
        if too many jobs are already queued/running.

        `owner` should be the submitter's JWT `sub` claim (or `None` if auth
        is disabled) -- see `ConversionJob.is_visible_to()`.
        """
        job = ConversionJob(
            id=str(uuid.uuid4()), source_format=source_format, name=name, owner=owner
        )
        with self._lock:
            pending = sum(1 for j in self._jobs.values() if j.status not in _TERMINAL_STATUSES)
            if pending >= self._max_pending:
                raise JobQueueFull(
                    f"{pending} conversions already queued/running (limit {self._max_pending})"
                )
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, fn)
        return job

    def _run(self, job: ConversionJob, fn: Callable[[], Path]) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        try:
            job.result_path = fn()
            job.status = JobStatus.SUCCEEDED
        except Exception as exc:
            # Full detail server-side only -- `job.error` round-trips to
            # HTTP/WebSocket clients via `to_dict()` and must not leak
            # internal paths (work_dir, tempfile.gettempdir(), ...) or
            # library internals.
            logger.exception("Conversion job %s failed", job.id)
            job.error = f"Conversion failed: {type(exc).__name__} (job id {job.id})"
            job.status = JobStatus.FAILED
        finally:
            job.finished_at = time.time()

    def _check_stall(self, job: ConversionJob) -> None:
        """Mark a job FAILED if it's been RUNNING past `stall_timeout_seconds`.

        See the class docstring: this only updates the reported status, it
        does not stop the underlying worker thread.
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
            job.error = (
                f"Conversion timed out after {self._stall_timeout_seconds / 60:.0f} minutes"
            )
            job.status = JobStatus.FAILED
            job.finished_at = time.time()

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
