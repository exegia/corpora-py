"""FastAPI router exposing corpus validation over HTTP.

This mirrors the ``validate_corpus`` MCP tool (``corpora_mcp.server``) as a
plain REST endpoint for the desktop app's non-MCP surface: after a conversion
(or a corpus dropped on disk) the app can confirm the ``.tf -> .cfm -> mmap``
cycle round-trips before trusting the dataset.

It lives in ``admin.services`` (not in the umbrella ``corpora_py`` package)
because API surfaces belong here — the umbrella package's role is to mount
routers, not define them. This keeps the split clear: umbrella orchestrates,
admin implements.

Like ``/convert``, every route here is gated by ``AuthMiddleware`` simply by
being mounted on the combined app. Validation by ``corpus``/``path`` is
stateless (it reads a directory and returns a verdict), but validation by
``job_id`` targets another user's potential job, so it applies the same
visibility rule as ``GET /convert/{id}``: a job that exists but isn't yours
404s exactly like an unknown id.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from corpora_mcp.corpus import corpus_manager
from corpora_mcp.validate import validate_corpus, validate_corpus_archive
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from .jobs import JobStatus, job_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["Validation"])


class ValidationRequest(BaseModel):
    """Target of a validation run: a conversion job, a loaded corpus, or a path."""

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
    job_id: str | None = Field(
        default=None,
        description=(
            "Validate the finished `.corpus` archive of a succeeded conversion "
            "job (overrides path and corpus). This is how the desktop app "
            "validates a just-converted upload without knowing server paths."
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


def _resolve_job_target(payload: ValidationRequest, request: Request) -> tuple[str, Path]:
    """Resolve a ``job_id`` request to the job's finished ``.corpus`` archive.

    Applies the same visibility rule as ``GET /convert/{id}`` (see
    ``admin.services.api._not_found_unless_visible``): a job that exists but
    belongs to a different submitter 404s identically to an unknown id, so
    this endpoint can't be used to enumerate other users' job ids either.
    """
    claims = getattr(request.state, "user", None)
    job = job_manager.get(payload.job_id)  # type: ignore[arg-type]
    if job is None or not job.is_visible_to(claims):
        raise HTTPException(status_code=404, detail="Unknown job id")
    if job.status != JobStatus.SUCCEEDED or job.result_path is None:
        raise HTTPException(
            status_code=409, detail=f"Job is {job.status.value}, not ready"
        )
    return payload.corpus or job.name, job.result_path


def _resolve_target(payload: ValidationRequest, request: Request) -> tuple[str, Path]:
    """Resolve the request to a (name, path) pair, or raise HTTP 404.

    ``job_id`` wins over ``path``, which wins over ``corpus`` (mirroring the
    ``validate_corpus`` MCP tool for the latter two); with none given, the
    current loaded corpus supplies the directory.
    """
    if payload.job_id is not None:
        return _resolve_job_target(payload, request)

    if payload.path is not None:
        target_path = Path(payload.path).expanduser()
        name = payload.corpus or target_path.name
    else:
        try:
            target_path = corpus_manager.get_path(payload.corpus)
        except (KeyError, RuntimeError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        name = payload.corpus or corpus_manager.current or target_path.name

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Corpus path not found: {target_path}")

    return name, target_path


@router.post("", response_model=ValidationResponse)
async def validate(payload: ValidationRequest, request: Request) -> ValidationResponse:
    """Validate a corpus through the full Context-Fabric load cycle.

    Returns 200 with ``valid: false`` and the reasons when the dataset loads but
    fails validation -- an invalid corpus is a result, not a bad request. Only a
    missing corpus/path/job (unresolvable target) is a 404.
    """
    name, target_path = _resolve_target(payload, request)

    # Blocking, CPU-bound load cycle (text-fabric / cfabric are synchronous);
    # run it off the event loop so the server stays responsive. A file is
    # treated as a packaged `.corpus` archive (whose shipped `.cfm` is checked
    # too); a directory as a raw Text-Fabric dataset.
    if target_path.is_file():
        result = await asyncio.to_thread(
            validate_corpus_archive, target_path, payload.corpus
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
