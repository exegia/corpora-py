"""FastAPI router exposing the Hub corpus storage (`storage.py`) over HTTP.

Mirrors the `storage_*` MCP tools (`storage_mcp.py`) as plain REST endpoints
for the desktop app's non-MCP surface, the same split `validation_api.py`
has with the `validate_corpus` tool. Like every router here it is mounted by
the combined app (`corpora_py.app`) and gated by its `AuthMiddleware`.

Uploads are job-first: `POST /storage` names a *succeeded conversion job*
and pushes that job's finished `.corpus` archive, applying the same
visibility rule as `GET /convert/{id}` (someone else's job 404s exactly like
an unknown id). A server-side `path` is also accepted for archives already
on disk, matching `/validate`'s precedent for this local-sidecar deployment.

Every `CorpusStorage` call is a blocking network operation, so handlers run
them through `asyncio.to_thread` to keep the event loop responsive.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from .jobs import JobStatus, job_manager
from .storage import (
    CorpusNotFoundError,
    StorageError,
    StorageNotConfiguredError,
    StoredCorpus,
    corpus_storage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["Storage"])

# Where `GET /storage/{filename}/download` materializes archives fetched from
# the Hub before streaming them back. Like `_RESULTS_ROOT` (`api.py`) nothing
# reaps this yet -- same TTL-cleanup gap, tracked in `packages/admin/CLAUDE.md`.
_HUB_CACHE_ROOT = Path(tempfile.gettempdir()) / "corpora-admin-hub-cache"

async def _run[T](fn: Callable[[], T]) -> T:
    """Run one blocking storage call off the event loop, mapping errors to HTTP.

    503 for "storage never configured" (server-side setup problem, retrying
    won't help until an operator sets `HF_STORAGE_REPO`), 404 for a missing
    archive, 502 for anything the Hub itself rejected.
    """
    try:
        return await asyncio.to_thread(fn)
    except StorageNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class StoredCorpusResponse(BaseModel):
    """One archive in the Hub storage repo (see `storage.StoredCorpus`)."""

    filename: str
    size_bytes: int | None
    repo_id: str
    url: str


class UploadRequest(BaseModel):
    """Source of an upload: a succeeded conversion job or a server-side path."""

    job_id: str | None = Field(
        default=None,
        description=(
            "Upload the finished `.corpus` archive of a succeeded conversion "
            "job. This is how the desktop app publishes a just-converted "
            "upload without knowing server paths."
        ),
    )
    path: str | None = Field(
        default=None,
        description="Upload a `.corpus` archive already on the server's disk instead.",
    )
    filename: str | None = Field(
        default=None,
        description=(
            "Name to store the archive under (`.corpus` appended if missing). "
            "Defaults to the job name or the local filename."
        ),
    )

    @model_validator(mode="after")
    def _require_source(self) -> UploadRequest:
        if self.job_id is None and self.path is None:
            raise ValueError("Provide either job_id or path")
        return self


def _resolve_upload_source(payload: UploadRequest, request: Request) -> tuple[Path, str | None]:
    """Resolve the request to a (local archive path, default filename) pair.

    `job_id` wins over `path` and applies the `/convert` visibility rule: a
    job that exists but belongs to a different submitter 404s identically to
    an unknown id, so this endpoint can't enumerate other users' job ids.
    """
    if payload.job_id is not None:
        claims = getattr(request.state, "user", None)
        job = job_manager.get(payload.job_id)
        if job is None or not job.is_visible_to(claims):
            raise HTTPException(status_code=404, detail="Unknown job id")
        if job.status != JobStatus.SUCCEEDED or job.result_path is None:
            raise HTTPException(
                status_code=409, detail=f"Job is {job.status.value}, not ready"
            )
        return job.result_path, payload.filename or f"{job.name}.corpus"

    local = Path(payload.path).expanduser()  # type: ignore[arg-type]
    if not local.is_file():
        raise HTTPException(status_code=404, detail=f"No archive at {local}")
    return local, payload.filename


def _response(stored: StoredCorpus) -> StoredCorpusResponse:
    return StoredCorpusResponse(
        filename=stored.filename,
        size_bytes=stored.size_bytes,
        repo_id=stored.repo_id,
        url=stored.url,
    )


@router.get("", response_model=list[StoredCorpusResponse])
async def list_stored_corpora() -> list[StoredCorpusResponse]:
    """List every `.corpus` archive in the Hub storage repo."""
    return [_response(s) for s in await _run(corpus_storage.list)]


@router.get("/{filename}", response_model=StoredCorpusResponse)
async def get_stored_corpus(filename: str) -> StoredCorpusResponse:
    """Metadata for one stored archive."""
    return _response(await _run(lambda: corpus_storage.info(filename)))


@router.post("", response_model=StoredCorpusResponse, status_code=201)
async def upload_corpus(payload: UploadRequest, request: Request) -> StoredCorpusResponse:
    """Push a finished `.corpus` archive to the Hub storage repo."""
    local, filename = _resolve_upload_source(payload, request)
    stored = await _run(lambda: corpus_storage.upload(local, filename))
    logger.info("Stored corpus %s (%s)", stored.filename, stored.repo_id)
    return _response(stored)


@router.get("/{filename}/download")
async def download_stored_corpus(filename: str) -> FileResponse:
    """Fetch one archive from the Hub and stream it back to the client."""
    local = await _run(
        lambda: corpus_storage.download(filename, dest_dir=_HUB_CACHE_ROOT)
    )
    return FileResponse(local, filename=local.name)


@router.delete("/{filename}", status_code=204)
async def delete_stored_corpus(filename: str) -> None:
    """Remove one archive from the Hub storage repo."""
    await _run(lambda: corpus_storage.delete(filename))
