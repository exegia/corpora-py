"""WebSocket endpoint for pushing conversion job status updates.

This is a convenience layer over `JobManager` (`jobs.py`), not a source of
fine-grained progress: the conversion pipeline (`admin.converters`,
`admin.converters._walker.convert_document`) has no progress hook, and
`Parser.iter_units()` is an unbounded generator with no known total unit
count up front. So the server can only report coarse status transitions
(queued -> running -> succeeded/failed), never "record 4213 of 31000" or a
percentage. See `packages/admin/CLAUDE.md` before wiring in real progress --
that requires threading a callback through every `_{format}_to_tf.py`
converter and `_walker.convert_document()`, not just this endpoint.

Given that ceiling, this still beats plain REST polling for UX on a
multi-minute conversion (a full Bible, a large EPUB): the client opens one
connection and is pushed the terminal state the instant it happens, instead
of guessing a polling interval and burning idle requests. It's not a
replacement for `GET /convert/{id}` -- that endpoint remains the source of
truth and the only option for clients that can't hold a socket open (behind
strict proxies, serverless callers, etc.).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .jobs import JobStatus, job_manager

router = APIRouter()

_POLL_INTERVAL_SECONDS = 0.5
_UNKNOWN_JOB_CLOSE_CODE = 4404  # application-defined range (4000-4999)


@router.websocket("/convert/{job_id}/ws")
async def conversion_status_ws(websocket: WebSocket, job_id: str) -> None:
    """Push `ConversionJob.to_dict()` snapshots whenever the job's status changes.

    Closes automatically once the job reaches a terminal state
    (`succeeded`/`failed`), or immediately with 4404 if `job_id` is unknown
    *or* belongs to a different submitter -- same non-distinguishing
    treatment as `GET /convert/{id}` (see `admin.services.api`), so a client
    can't use this to enumerate other users' job ids. The claims used for
    that check are whatever `AuthMiddleware` (`corpora_py.auth`) attached to
    this connection's ASGI scope -- `None` if auth is currently disabled.
    """
    claims = getattr(websocket.state, "user", None)
    job = job_manager.get(job_id)
    if job is None or not job.is_visible_to(claims):
        await websocket.close(code=_UNKNOWN_JOB_CLOSE_CODE, reason="Unknown job id")
        return

    await websocket.accept()
    last_status: JobStatus | None = None
    try:
        while True:
            job = job_manager.get(job_id)
            if job is None:
                break
            if job.status != last_status:
                await websocket.send_json(job.to_dict())
                last_status = job.status
            if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
                break
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
    await websocket.close()
