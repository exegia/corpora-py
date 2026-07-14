"""FastAPI router exposing corpus validation over HTTP.

This mirrors the ``validate_corpus`` MCP tool (``corpora_mcp.server``) as a
plain REST endpoint for the desktop app's non-MCP surface: after a conversion
(or a corpus dropped on disk) the app can confirm the ``.tf -> .cfm -> mmap``
cycle round-trips before trusting the dataset.

It lives in ``corpora_py`` (the umbrella package), not ``admin`` or
``corpora_mcp``, for the same reason ``app.py`` does: the umbrella already
depends on both ``corpora-mcp`` (for the validation logic + ``corpus_manager``)
and ``corpora-admin``, whereas neither of those depends on the other. Putting
this in ``admin`` would force an ``admin -> corpora-mcp`` dependency and
collapse the slim-client/heavy-admin split described in the root ``CLAUDE.md``.

Like ``/convert``, every route here is gated by ``AuthMiddleware`` simply by
being mounted on the combined app; there is no per-resource ownership to
enforce because validation is stateless (it reads a directory and returns a
verdict -- nothing is created, stored, or scoped to a submitter).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from corpora_mcp.corpus import corpus_manager
from corpora_mcp.validate import validate_corpus, validate_corpus_archive
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["Validation"])


class ValidationRequest(BaseModel):
    """Target of a validation run: a loaded corpus by name, or a path on disk."""

    corpus: str | None = Field(
        default=None,
        description="Name of a loaded corpus to validate. Defaults to the current corpus.",
    )
    path: str | None = Field(
        default=None,
        description=(
            "Validate a dataset directory or a packaged `.corpus` archive on "
            "disk instead (overrides corpus). For a `.corpus` archive the "
            "shipped `.cfm` cache is checked against a `.tf` recompile."
        ),
    )

    @model_validator(mode="after")
    def _require_target(self) -> ValidationRequest:
        # Both may be omitted only when a corpus is already loaded (falls back
        # to the current corpus); that case is resolved in the handler, which
        # returns a clean 404 if there is nothing loaded. Nothing to reject here.
        return self


class ValidationResponse(BaseModel):
    """Structured validation verdict (see ``ValidationResult.summary``)."""

    corpus: str
    path: str
    valid: bool
    stats: dict[str, int] | None
    reasons: list[str]
    checks: dict[str, Any]


def _resolve_target(request: ValidationRequest) -> tuple[str, Path]:
    """Resolve the request to a (name, directory) pair, or raise HTTP 404.

    Mirrors the ``validate_corpus`` MCP tool: ``path`` wins over ``corpus``;
    otherwise the named (or current) loaded corpus supplies the directory.
    """
    if request.path is not None:
        target_path = Path(request.path).expanduser()
        name = request.corpus or target_path.name
    else:
        try:
            target_path = corpus_manager.get_path(request.corpus)
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        name = request.corpus or corpus_manager.current or target_path.name

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Corpus path not found: {target_path}")

    return name, target_path


@router.post("", response_model=ValidationResponse)
async def validate(request: ValidationRequest) -> ValidationResponse:
    """Validate a corpus through the full Context-Fabric load cycle.

    Returns 200 with ``valid: false`` and the reasons when the dataset loads but
    fails validation -- an invalid corpus is a result, not a bad request. Only a
    missing corpus/path (unresolvable target) is a 404.
    """
    name, target_path = _resolve_target(request)

    # Blocking, CPU-bound load cycle (text-fabric / cfabric are synchronous);
    # run it off the event loop so the server stays responsive. A file is
    # treated as a packaged `.corpus` archive (whose shipped `.cfm` is checked
    # too); a directory as a raw Text-Fabric dataset.
    if target_path.is_file():
        result = await asyncio.to_thread(
            validate_corpus_archive, target_path, request.corpus
        )
    else:
        result = await asyncio.to_thread(validate_corpus, name, target_path)

    summary = result.summary()
    return ValidationResponse(
        corpus=result.corpus,
        path=str(target_path),
        valid=summary["valid"],
        stats=summary["stats"],
        reasons=summary["reasons"],
        checks=summary["checks"],
    )
