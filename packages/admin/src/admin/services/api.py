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

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..converters import CONVERTERS
from ..converters.convert_to_corpus import convert_to_corpus
from ..parsers.schema import SourceFormat
from .jobs import JobStatus, job_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/convert", tags=["Conversion"])

# Scratch space for uploads + intermediate Text-Fabric output. Each job gets
# its own subdirectory (named after the job id) so concurrent conversions
# never collide; nothing here is meant to be long-lived storage -- once
# packaged into a `.corpus` archive, the caller is expected to move/upload
# the result and the job directory can be reaped.
_WORK_ROOT = Path(tempfile.gettempdir()) / "corpora-admin-jobs"

# 1 MiB read chunks: large enough to not be I/O-bound, small enough that a
# multi-hundred-MB EPUB/PDF is never fully buffered in memory.
_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    """Stream `upload` to disk in chunks.

    Uploading is comparatively cheap disk I/O next to the conversion itself
    (which runs in the background thread pool), so doing this directly in
    the request coroutine -- rather than also punting it to a worker thread
    -- is an acceptable, deliberate trade-off for keeping the endpoint
    simple. What must never happen is buffering the whole file in memory
    (`await upload.read()` with no size limit), which is why this reads in
    fixed-size chunks.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (upload.filename or "source")
    with dest.open("wb") as out:
        while chunk := await upload.read(_UPLOAD_CHUNK_SIZE):
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
    async endpoint.
    """
    converter = CONVERTERS[source_format]
    tf_dir = work_dir / "tf"
    converter(str(source_path), tf_dir)
    corpus_path = work_dir / f"{name}.corpus"
    return convert_to_corpus(tf_dir, corpus_path, name=name, description=description)

    # Minted up front (rather than reading `job.id` off the object
    # `job_manager.submit()` returns) so the `fn` closure below can call
    # `job_manager.log(job_id, ...)` from inside the worker thread --
    # referencing the not-yet-returned `job` object here would race the
    # executor, which can start running `fn` before `submit()` returns.
    job_id = str(uuid.uuid4())

@router.post("", status_code=202)
async def create_conversion(
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

    _WORK_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="job-", dir=str(_WORK_ROOT)))
    source_path = await _save_upload(file, work_dir / "source")

    job = job_manager.submit(
        source_format=source_format,
        name=name,
        fn=lambda: _run_conversion(
            source_path=source_path,
            work_dir=work_dir,
            source_format=source_format,
            name=name,
            description=description,
        ),
    )
    logger.info("Queued conversion job %s (%s, %s)", job.id, source_format.value, name)
    return {
        "job_id": job.id,
        "status_url": f"/convert/{job.id}",
        "ws_url": f"/convert/{job.id}/ws",
    }


@router.get("/{job_id}")
async def get_conversion(job_id: str) -> dict[str, object]:
    """Poll the status of a conversion job."""
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return job.to_dict()


@router.get("/{job_id}/download")
async def download_conversion(job_id: str) -> FileResponse:
    """Download the finished `.corpus` archive for a succeeded job."""
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    if job.status != JobStatus.SUCCEEDED or job.result_path is None:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not ready")
    return FileResponse(job.result_path, filename=job.result_path.name)
