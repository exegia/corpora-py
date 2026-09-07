"""HTTP surface for reference identifiers over stored corpora (`reference.py`).

Three routes, all read-only (no Hub writes, so `HF_READ_ONLY` does not apply):

    POST /refs                 node(s) -> reference      (user clicked a node)
    GET  /refs/resolve?ref=…   reference -> node(s) + corpus metadata
    GET  /refs/shortcode?ref=… reference -> label / pill / share URL bundle
    POST /refs/shortcode       same, from a corpus + node instead of a string

Errors map to the status a client can act on: 400 for a string the grammar
rejects, 404 for a corpus/section/node that does not exist, 409 when the
reference pins a version other than the one stored, 503/502 for storage.
Blocking corpus loads run via `asyncio.to_thread` like the other routers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from common.utils import tfref
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import reference
from .storage import CorpusNotFoundError, StorageError, StorageNotConfiguredError

router = APIRouter(prefix="/refs", tags=["References"])


async def _run[T](fn: Callable[[], T]) -> T:
    try:
        return await asyncio.to_thread(fn)
    except tfref.ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except tfref.VersionMismatch as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "wanted": exc.wanted, "loaded": exc.loaded},
        ) from exc
    except (tfref.SectionNotFound, tfref.TypeNotInSection, tfref.IndexOutOfRange) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StorageNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class ReferenceCreate(BaseModel):
    """A node the user selected, optionally the last node of a same-type range."""

    corpus: str = Field(description="Library filename (`bhsa.corpus`) or its stem (`bhsa`).")
    node: int = Field(ge=1)
    end_node: int | None = Field(default=None, ge=1, description="Inclusive end of a range.")
    lang: str | None = Field(default=None, description="Heading language for multilingual corpora.")


@router.post("")
async def create_reference(body: ReferenceCreate) -> dict[str, Any]:
    """Turn a clicked node (or node range) into a versioned, shareable reference."""
    return await _run(
        lambda: reference.create_reference(body.corpus, body.node, body.end_node, lang=body.lang)
    )


@router.get("/resolve")
async def resolve_reference(
    ref: str = Query(description="Short form (`bhsa@1.0/Deut:4:2!clause1`) or `urn:tf:` form."),
    corpus: str | None = Query(
        default=None, description="Override / supply the corpus when the reference has none."
    ),
    lang: str | None = Query(default=None),
) -> dict[str, Any]:
    """Resolve a reference to its node(s) plus the parent corpus's metadata."""
    return await _run(lambda: reference.resolve_reference(ref, corpus, lang=lang))


@router.get("/shortcode")
async def shortcode_from_ref(
    ref: str = Query(description="Reference to present."),
    corpus: str | None = Query(default=None),
    url_template: str | None = Query(
        default=None, description="Override REFERENCE_URL_TEMPLATE; `{ref}` is substituted."
    ),
) -> dict[str, Any]:
    """Label, compact pill token, share URL and copy-paste snippets for a reference."""
    return await _run(lambda: reference.shortcode(ref, filename=corpus, url_template=url_template))


class ShortcodeCreate(ReferenceCreate):
    url_template: str | None = None


@router.post("/shortcode")
async def shortcode_from_node(body: ShortcodeCreate) -> dict[str, Any]:
    """Same bundle as GET /refs/shortcode, built straight from a node selection."""
    return await _run(
        lambda: reference.shortcode(
            None,
            filename=body.corpus,
            node=body.node,
            end_node=body.end_node,
            url_template=body.url_template,
        )
    )
