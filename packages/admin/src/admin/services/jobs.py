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


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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


class JobManager:
    """Tracks conversion jobs and runs them on a background thread pool.

    A process-local singleton is sufficient here: conversion output lands on
    local disk (see `convert_to_corpus`), so a multi-worker/multi-process
    deployment would need a shared store + queue (Redis, Celery, ...) instead
    of this in-memory registry. That's a deliberate scope cut for a
    single-process admin/conversion service, not an oversight -- revisit if
    this ever needs to run behind more than one uvicorn worker.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, ConversionJob] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="convert")

    def submit(
        self,
        *,
        source_format: SourceFormat,
        name: str,
        fn: Callable[[], Path],
    ) -> ConversionJob:
        """Register a new job and hand `fn` to the worker pool.

        `fn` must be a zero-argument callable that does the actual blocking
        conversion work and returns the path to the finished `.corpus` file
        (or raises on failure).
        """
        job = ConversionJob(id=str(uuid.uuid4()), source_format=source_format, name=name)
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, fn)
        return job

    def _run(self, job: ConversionJob, fn: Callable[[], Path]) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        try:
            job.result_path = fn()
            job.status = JobStatus.SUCCEEDED
        except Exception as exc:  # noqa: BLE001 -- surfaced to the client, not swallowed
            job.error = str(exc)
            job.status = JobStatus.FAILED
        finally:
            job.finished_at = time.time()

    def get(self, job_id: str) -> ConversionJob | None:
        with self._lock:
            return self._jobs.get(job_id)


# Process-wide singleton, mirroring `corpus_manager` in `corpora_mcp.corpus`.
job_manager = JobManager()
