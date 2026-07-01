"""FastAPI router exposing document conversion (parse -> Text-Fabric -> .cfm
-> .corpus) as an HTTP API.

This module only builds an `APIRouter`, not a standalone `FastAPI` app --
`admin` has no business owning CORS policy, auth, or the docs title; that's
the combined app's job (see `corpora_py.app`), which already depends on both
`corpora-admin` and `corpora-mcp`. Keeping `admin` router-only avoids an
`admin -> corpora-mcp` (or `admin -> corpora_py`) dependency that would
collapse the slim-client/heavy-admin split described in the root `CLAUDE.md`.

Conversion of a large source (a full Bible, a multi-hundred-page EPUB) can
take from seconds to several minutes and pins a CPU core the whole time
(text-fabric, lxml, and pypdf are all synchronous, non-async libraries).
Every endpoint here is fire-and-poll: `POST /convert` streams the upload to
disk and hands the actual conversion to `JobManager` (a background thread
pool, see `jobs.py`) so the request returns immediately with a job id.
`GET /convert/{id}` (poll) and `/convert/{id}/ws` (push, see `websocket.py`)
are how a client finds out when it's done.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..converters import CONVERTERS
from ..converters.convert_to_corpus import convert_to_corpus
from ..parsers.schema import SourceFormat
from .jobs import ConversionJob, JobQueueFullError, JobStatus, job_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/convert", tags=["Conversion"])

# Scratch space for uploads + intermediate Text-Fabric output. Each job gets
# its own subdirectory (named after the job id) so concurrent conversions
# never collide. Deleted in full once the job reaches a terminal state (see
# `_run_conversion`'s `finally` block) -- nothing here is meant to survive a
# finished job.
_WORK_ROOT = Path(tempfile.gettempdir()) / "corpora-admin-jobs"

# Where finished `.corpus` archives live, named after their (already-unique)
# `work_dir` so no separate id has to be threaded through `JobManager`.
# Unlike `_WORK_ROOT`, nothing currently deletes from here -- there is no
# "client downloaded it, safe to delete" signal, and a naive delete-on-
# download would break retries. This still needs a TTL-based reap job; see
# `packages/admin/CLAUDE.md`'s "Known gaps".
_RESULTS_ROOT = Path(tempfile.gettempdir()) / "corpora-admin-results"

# 1 MiB read chunks: large enough to not be I/O-bound, small enough that a
# multi-hundred-MB EPUB/PDF is never fully buffered in memory.
_UPLOAD_CHUNK_SIZE = 1024 * 1024

# Reject uploads past this size. This only bounds disk usage *during* the
# chunked read (the request body itself is already being streamed, not
# buffered) -- it's not a pre-flight `Content-Length` check, since
# `UploadFile`'s multipart parsing doesn't expose the declared size before
# parsing starts. 500 MiB comfortably covers a full Bible EPUB or a large
# scanned PDF; raise it if a legitimate source needs more.
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _claims(request: Request) -> dict[str, Any] | None:
    """The decoded JWT claims `AuthMiddleware` attached to this request.

    `None` if auth is currently disabled (`AUTH_REQUIRED=false`) -- see
    `corpora_py.auth`. Only ever reads `request.state`, never verifies
    anything itself: this router has no auth policy of its own (see this
    module's docstring).
    """
    return getattr(request.state, "user", None)


def _not_found_unless_visible(job: ConversionJob | None, request: Request) -> ConversionJob:
    if job is None or not job.is_visible_to(_claims(request)):
        # Same message/status for "doesn't exist" and "exists but isn't
        # yours" -- distinguishing the two would let a client enumerate
        # other users' job ids.
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job


async def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    """Stream `upload` to disk in chunks, enforcing `_MAX_UPLOAD_BYTES`.

    Uploading is comparatively cheap disk I/O next to the conversion itself
    (which runs in the background thread pool), so doing this directly in
    the request coroutine -- rather than also punting it to a worker thread
    -- is an acceptable, deliberate trade-off for keeping the endpoint
    simple. What must never happen is buffering the whole file in memory
    (`await upload.read()` with no size limit), which is why this reads in
    fixed-size chunks.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    # `.name` strips any path segments from the client-supplied filename
    # (e.g. `../../etc/passwd` -> `passwd`) before joining with `dest_dir`.
    # A filename of exactly "." is the one input where `.name` returns an
    # empty string (`Path("..").name` is `".."`, not empty, but joining
    # that back onto `dest_dir` just re-selects `dest_dir`'s parent entry,
    # same failure mode) -- either way `dest_dir / ""` or `dest_dir / ".."`
    # resolves to an existing directory, not a new file, so `.open("wb")`
    # below would raise `IsADirectoryError` instead of a clean 4xx. Reject
    # both explicitly rather than let that surface as an unhandled 500.
    filename = Path(upload.filename or "source").name or "source"
    if filename in (".", ".."):
        raise HTTPException(status_code=422, detail="Invalid upload filename")
    dest = dest_dir / filename
    total = 0
    with dest.open("wb") as out:
        while chunk := await upload.read(_UPLOAD_CHUNK_SIZE):
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit",
                )
            out.write(chunk)
    return dest


def _run_conversion(
    *,
    source_path: Path,
    work_dir: Path,
    source_format: SourceFormat,
    name: str,
    description: str,
) -> Path:
    """Blocking pipeline: parse -> Text-Fabric -> .cfm -> .corpus.

    Runs on a `JobManager` worker thread -- never call this directly from an
    async endpoint. Always cleans up `work_dir` (the upload + intermediate
    `tf/` tree) on the way out, success or failure -- only the final
    `.corpus`, written to `_RESULTS_ROOT`, survives.
    """
    try:
        converter = CONVERTERS[source_format]
        tf_dir = work_dir / "tf"
        converter(str(source_path), tf_dir)
        _RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        corpus_path = _RESULTS_ROOT / f"{work_dir.name}.corpus"
        return convert_to_corpus(tf_dir, corpus_path, name=name, description=description)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@router.post("", status_code=202)
async def create_conversion(
    request: Request,
    file: UploadFile,
    source_format: SourceFormat = Form(...),
    name: str = Form(...),
    description: str = Form(""),
) -> dict[str, str]:
    """Upload a source document and start converting it in the background.

    Returns immediately (202) with a job id -- the conversion itself has not
    finished yet. Poll `GET /convert/{job_id}` or open
    `ws://.../convert/{job_id}/ws` for status.
    """
    if source_format not in CONVERTERS:
        raise HTTPException(
            status_code=422,
            detail=f"No converter registered for {source_format!r}. "
            f"Available: {sorted(f.value for f in CONVERTERS)}",
        )

    claims = _claims(request)
    owner = claims.get("sub") if claims else None

    _WORK_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="job-", dir=str(_WORK_ROOT)))
    try:
        source_path = await _save_upload(file, work_dir / "source")

        try:
            job = job_manager.submit(
                source_format=source_format,
                name=name,
                owner=owner,
                fn=lambda: _run_conversion(
                    source_path=source_path,
                    work_dir=work_dir,
                    source_format=source_format,
                    name=name,
                    description=description,
                ),
            )
        except JobQueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception:
        # The job never started (rejected upload, full queue, or some
        # unexpected failure mid-upload e.g. a full disk) -- nothing will
        # clean up `work_dir` for us in any of those cases, so do it here
        # regardless of what went wrong. Deliberately broader than `except
        # HTTPException`: an unanticipated exception from `_save_upload`
        # must not leak `work_dir` just because it wasn't one of the
        # exceptions this function already knows how to raise.
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    logger.info("Queued conversion job %s (%s, %s)", job.id, source_format.value, name)
    return {
        "job_id": job.id,
        "status_url": f"/convert/{job.id}",
        "ws_url": f"/convert/{job.id}/ws",
    }


@router.get("/{job_id}")
async def get_conversion(job_id: str, request: Request) -> dict[str, object]:
    """Poll the status of a conversion job.

    404s for a job that exists but belongs to a different submitter, same as
    an unknown id -- see `_not_found_unless_visible`.
    """
    job = _not_found_unless_visible(job_manager.get(job_id), request)
    return job.to_dict()


@router.get("/{job_id}/download")
async def download_conversion(job_id: str, request: Request) -> FileResponse:
    """Download the finished `.corpus` archive for a succeeded job."""
    job = _not_found_unless_visible(job_manager.get(job_id), request)
    if job.status != JobStatus.SUCCEEDED or job.result_path is None:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not ready")
    return FileResponse(job.result_path, filename=job.result_path.name)
