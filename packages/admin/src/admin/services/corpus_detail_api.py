"""FastAPI router exposing corpus-detail over HTTP (`corpus_detail.py`).

Adds a *detail* surface on top of the flat `/storage` library
(`storage_api.py`) for the desktop app: read/patch a stored archive's manifest,
fetch its section index, and read its content by reference. It shares the
`/storage/{filename}` path space with the storage router -- the extra path
segment (`/manifest`, `/index`, `/content`) keeps every route distinct, so
 the inclusion order is irrelevant.

Like every router here it is mounted by the combined app (`corpora_py.app`) and
gated by its `AuthMiddleware`. Each `corpus_detail` call is blocking (Hub I/O,
zip extraction, cfabric loading), so handlers run them through
`asyncio.to_thread`, mapping errors exactly as `storage_api._run` does: 503 when
storage was never configured, 404 for a missing archive or bad reference, 502
for anything the Hub itself rejected.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator

from .corpus_detail import (
    annotate_node,
    get_content,
    get_index,
    get_manifest,
    get_node,
    get_sections,
    update_manifest,
)
from .storage import (
    CorpusNotFoundError,
    ReadOnlyStorageError,
    StorageError,
    StorageNotConfiguredError,
)
from .storage_api import require_writable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["Corpus Detail"])


async def _run[T](fn: Callable[[], T]) -> T:
    """Run one blocking corpus-detail call off the event loop, mapping errors to HTTP.

    Identical mapping to `storage_api._run`: 503 for "storage never configured",
    404 for a missing archive or an unresolvable section reference, 502 for
    anything the Hub itself rejected.
    """
    try:
        return await asyncio.to_thread(fn)
    except StorageNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ReadOnlyStorageError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class ManifestUpdate(BaseModel):
    """Editable subset of an archive's manifest. All fields optional strings.

    An empty body is rejected (422): a PATCH must change at least one field. A
    field set to `""` is a legitimate value, not "unset" -- `model_fields_set`
    distinguishes the two.
    """

    name: str | None = None
    description: str | None = None
    version: str | None = None
    language: str | None = None
    languageCode: str | None = None  # noqa: N815 - matches manifest key
    type: str | None = None
    category: str | None = None
    written_date: str | None = None

    @model_validator(mode="after")
    def _require_one(self) -> ManifestUpdate:
        if not self.model_fields_set:
            raise ValueError("Provide at least one manifest field to update")
        return self


@router.get("/{filename}/manifest")
async def get_corpus_manifest(filename: str) -> dict[str, Any]:
    """Return the stored archive's ``manifest.yml`` (unknown keys preserved)."""
    return await _run(lambda: get_manifest(filename))


@router.patch("/{filename}/manifest", dependencies=[Depends(require_writable)])
async def patch_corpus_manifest(
    filename: str, payload: ManifestUpdate
) -> dict[str, Any]:
    """Patch a subset of the manifest, re-upload the archive, return the full manifest."""
    updates = payload.model_dump(exclude_unset=True)
    return await _run(lambda: update_manifest(filename, updates))


class NodeAnnotation(BaseModel):
    """Node-correction payload: the corrected type and/or a rationale note.

    An empty body is rejected (422) -- a PATCH must provide at least one of
    the two. The converter's original type is recorded server-side
    (`converted_otype`), never supplied by the client.
    """

    otype: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _require_one(self) -> NodeAnnotation:
        if not self.model_fields_set:
            raise ValueError("Provide otype and/or note to annotate a node")
        return self


@router.get("/{filename}/nodes/{node}")
async def get_corpus_node(filename: str, node: int) -> dict[str, Any]:
    """Inspect one graph node: type, slot span, text, features, annotation."""
    return await _run(lambda: get_node(filename, node))


@router.patch("/{filename}/nodes/{node}", dependencies=[Depends(require_writable)])
async def patch_corpus_node(
    filename: str, node: int, payload: NodeAnnotation
) -> dict[str, Any]:
    """Record a node-type correction in the archive's annotations sidecar."""
    updates = payload.model_dump(exclude_unset=True)
    return await _run(lambda: annotate_node(filename, node, **updates))


@router.get("/{filename}/index")
async def get_corpus_index(filename: str) -> dict[str, Any]:
    """Return the archive's toc, section structure, and node-type stats.

    ``node_types`` entries include ``avg_slots`` and ``is_slot``. Each section
    item includes ``child_count``, ``words`` (slot span), and ``truncated``
    when the nested children list was capped. Deeper / remaining children:
    ``GET /storage/{filename}/sections``.
    """
    return await _run(lambda: get_index(filename))


@router.get("/{filename}/sections")
async def get_corpus_sections(
    filename: str,
    parent: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50),
) -> dict[str, Any]:
    """Paginated section children under ``parent`` (top-level if omitted).

    Lowest-level sections return no items — use ``/content`` for passages.
    """
    return await _run(
        lambda: get_sections(filename, parent=parent, offset=offset, limit=limit)
    )


@router.get("/{filename}/content")
async def get_corpus_content(
    filename: str,
    ref: str | None = Query(default=None),
    fmt: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50),
) -> dict[str, Any]:
    """Return paginated passages under `ref` (or the whole corpus if omitted)."""
    return await _run(
        lambda: get_content(filename, ref=ref, fmt=fmt, offset=offset, limit=limit)
    )
