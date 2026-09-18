"""Owned working-draft creation, reader views, and archive export."""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from . import drafts
from .router import _mutation_call
from .schemas import DraftCreateRequest, DraftInfo, DraftListResponse, DraftReadResponse


def _private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/drafts", tags=["AI Working Drafts"], dependencies=[Depends(_private_response)]
)


@router.post("", response_model=DraftInfo)
async def create_draft(request: DraftCreateRequest) -> DraftInfo | JSONResponse:
    """Create one private working copy per owned completed conversion job; retries reuse it."""
    return await _mutation_call(drafts.create, request.job_id)


@router.get("", response_model=DraftListResponse)
async def list_drafts(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DraftListResponse | JSONResponse:
    return await _mutation_call(drafts.list_drafts, limit, offset)


@router.get("/{draft_id}", response_model=DraftInfo)
async def get_draft(draft_id: str) -> DraftInfo | JSONResponse:
    return await _mutation_call(drafts.get, draft_id)


@router.get("/{draft_id}/archive")
async def export_draft(draft_id: str):
    """Download verified current HEAD bytes, including feature edits and provenance."""
    result = await _mutation_call(drafts.export, draft_id)
    if isinstance(result, JSONResponse):
        return result
    temporary, info = result
    return FileResponse(
        Path(temporary.name) / "draft.corpus",
        media_type="application/zip",
        filename=info.id + ".corpus",
        background=BackgroundTask(temporary.cleanup),
        headers={
            "ETag": '"' + info.digest + '"',
            "X-Draft-Revision": info.revision,
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{draft_id}/manifest", response_model=DraftReadResponse)
async def manifest(draft_id: str) -> DraftReadResponse | JSONResponse:
    return await _mutation_call(drafts.read, draft_id, "manifest")


@router.get("/{draft_id}/index", response_model=DraftReadResponse)
async def index(draft_id: str) -> DraftReadResponse | JSONResponse:
    return await _mutation_call(drafts.read, draft_id, "index")


@router.get("/{draft_id}/versions", response_model=DraftReadResponse)
async def versions(draft_id: str) -> DraftReadResponse | JSONResponse:
    return await _mutation_call(drafts.read, draft_id, "versions")


@router.get("/{draft_id}/nodes/{node}", response_model=DraftReadResponse)
async def node(draft_id: str, node: int) -> DraftReadResponse | JSONResponse:
    return await _mutation_call(lambda: drafts.read(draft_id, "node", node=node))


@router.get("/{draft_id}/sections", response_model=DraftReadResponse)
async def sections(
    draft_id: str,
    parent: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DraftReadResponse | JSONResponse:
    return await _mutation_call(
        lambda: drafts.read(draft_id, "sections", parent=parent, offset=offset, limit=limit)
    )


@router.get("/{draft_id}/content", response_model=DraftReadResponse)
async def content(
    draft_id: str,
    ref: str | None = None,
    fmt: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DraftReadResponse | JSONResponse:
    return await _mutation_call(
        lambda: drafts.read(draft_id, "content", ref=ref, fmt=fmt, offset=offset, limit=limit)
    )
