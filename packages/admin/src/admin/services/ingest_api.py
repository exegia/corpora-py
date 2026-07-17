"""FastAPI router exposing Docling ingestion (document → Context Fabric v1
graph) as an HTTP API.

The sibling of `api.py` (`/convert`), for the canonical-graph pipeline
instead of the Text-Fabric one: `POST /ingest` uploads a document (PDF,
DOCX, PPTX, HTML, Markdown, images, …), parses it with Docling in the
background (`admin.ingest.parse_file` — layout analysis of a large PDF takes
seconds to minutes and pins a CPU core, so the same fire-and-poll `JobManager`
pattern applies), and the finished job serves a schema-validated `graph.json`
(see `admin.ingest.docling_graph.CanonicalGraph.to_dict`). Docling
auto-detects the input format — no `source_format` form field is needed.

Requires the `corpora-admin[docling]` extra at runtime; without it,
`POST /ingest` answers 503 instead of failing mid-job.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import uuid
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .api import _RESULTS_ROOT, _WORK_ROOT, _claims, _not_found_unless_visible, _save_upload
from .jobs import JobQueueFullError, JobStatus, job_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingestion"])

# Mirrors LangTag in common.defs.schema.json (and _LANG_TAG_RE in
# admin.ingest.docling_graph — deliberately NOT imported from there: this
# module must stay importable without `docling-core`, which slim serverless
# deployments exclude from the bundle; see `parse_file` below).
_LANG_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


def parse_file(source: Path, **kwargs: Any) -> Any:
    """Lazy indirection to `admin.ingest.parse_file`.

    `admin.ingest` imports `docling-core` (which pulls pandas + pillow) at
    module import time. Deferring that import to first use keeps this router
    — and therefore `corpora_py.app` — importable on slim deployments that
    exclude the whole docling-core chain from the bundle (Vercel; see
    vercel.json's installCommand). Requests still fail cleanly there:
    `create_ingestion` 503s on the missing `docling` package before any job
    is submitted. Tests monkeypatch THIS name to stub the parse.
    """
    from ..ingest import parse_file as _parse_file

    return _parse_file(source, **kwargs)


def _run_ingestion(
    *,
    source_path: Path,
    work_dir: Path,
    language: str,
    corpus_id: str | None,
    title: str | None,
    job_id: str,
) -> Path:
    """Blocking pipeline: Docling parse → canonical graph → graph.json.

    Runs on a `JobManager` worker thread. Mirrors `api._run_conversion`:
    only the final artifact, written to `_RESULTS_ROOT`, survives; the
    upload/work dir is always cleaned up.
    """
    try:
        job_manager.log(job_id, "Parsing document with Docling...")
        graph = parse_file(
            source_path,
            language=language,
            corpus_id=corpus_id,
            title=title or None,
        )
        job_manager.log(
            job_id,
            f"Extracted {len(graph.nodes)} nodes / {len(graph.fragments)} fragments. "
            "Writing graph.json...",
        )
        _RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        result_path = _RESULTS_ROOT / f"{work_dir.name}.graph.json"
        result_path.write_text(
            json.dumps(graph.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        job_manager.log(job_id, "Ingestion complete.")
        return result_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@router.post("", status_code=202)
async def create_ingestion(
    request: Request,
    file: UploadFile,
    name: str = Form(""),
    language: str = Form("und"),
    corpus_id: str = Form(""),
) -> dict[str, str]:
    """Upload a document and start extracting it to a Context Fabric graph.

    Returns immediately (202) with a job id; poll `GET /ingest/{job_id}` and
    download the finished `graph.json` from `GET /ingest/{job_id}/download`.
    `language` is the edition's BCP 47 tag (default `und` — undetermined);
    `corpus_id` optionally attaches the work to an existing corpus (UUID)
    instead of minting a single-document one; `name` overrides the title
    Docling detects.
    """
    if find_spec("docling") is None:
        raise HTTPException(
            status_code=503,
            detail="Docling is not installed on this server. "
            "Install the `corpora-admin[docling]` extra to enable /ingest.",
        )
    if not _LANG_TAG_RE.match(language):
        raise HTTPException(
            status_code=422, detail=f"Not a BCP 47 language tag: {language!r}"
        )
    if corpus_id:
        try:
            uuid.UUID(corpus_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="corpus_id must be a UUID"
            ) from exc

    claims = _claims(request)
    owner = claims.get("sub") if claims else None
    job_id = str(uuid.uuid4())

    _WORK_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="ingest-", dir=str(_WORK_ROOT)))
    try:
        source_path = await _save_upload(file, work_dir / "source")
        detected_format = source_path.suffix.lstrip(".").lower() or "docling"
        try:
            job = job_manager.submit(
                job_id=job_id,
                source_format=detected_format,
                name=name or source_path.name,
                owner=owner,
                fn=lambda: _run_ingestion(
                    source_path=source_path,
                    work_dir=work_dir,
                    language=language,
                    corpus_id=corpus_id or None,
                    title=name or None,
                    job_id=job_id,
                ),
            )
        except JobQueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception:
        # Same clean-up-on-any-failure rule as `api.create_conversion`.
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    logger.info("Queued ingestion job %s (%s, %s)", job.id, detected_format, job.name)
    return {
        "job_id": job.id,
        "status_url": f"/ingest/{job.id}",
        "download_url": f"/ingest/{job.id}/download",
    }


@router.get("/{job_id}")
async def get_ingestion(job_id: str, request: Request) -> dict[str, object]:
    """Poll the status of an ingestion job (same visibility rule as /convert)."""
    job = _not_found_unless_visible(job_manager.get(job_id), request)
    return job.to_dict()


@router.get("/{job_id}/download")
async def download_ingestion(job_id: str, request: Request) -> FileResponse:
    """Download the finished `graph.json` for a succeeded ingestion job."""
    job = _not_found_unless_visible(job_manager.get(job_id), request)
    if job.status != JobStatus.SUCCEEDED or job.result_path is None:
        raise HTTPException(
            status_code=409, detail=f"Job is {job.status.value}, not ready"
        )
    return FileResponse(
        job.result_path, filename=job.result_path.name, media_type="application/json"
    )
