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
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..converters import CONVERTERS
from ..converters.convert_to_corpus import convert_to_corpus
from ..parsers.schema import CorpusCategory, SourceFormat
from .conversion import (
    ConversionError,
    CorpusValidationError,
    clean_filename_stem,
    derive_display_name,
    extract_source_title,
    run_conversion,
    validate_archive,
)
from .corpus_detail import (
    annotate_node,
    diff_archives,
    get_content,
    get_index,
    get_manifest,
    get_node,
    get_sections,
    get_versions,
    register_local_archive,
    restore_from_snapshot,
    update_manifest,
)
from .corpus_detail_api import ManifestUpdate, NodeAnnotation
from .corpus_detail_api import _run as _run_detail
from .jobs import (
    _CORPUS_SUFFIX,
    ConversionJob,
    JobFailedError,
    JobQueueFullError,
    JobStatus,
    JobStoreError,
    JobStoreNotConfiguredError,
    SnapshotMissingError,
    _slugify,
    job_manager,
    result_filename_for,
    snapshot_key_for,
)
from .upload_validation import validate_upload

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

# Rendered into every conversion endpoint's /docs description (issue #104):
# the transport guidance lives in the OpenAPI, not just this repo's CLAUDE.md,
# because a WS-first client on a serverless deployment will hang mid-job.
_TRANSPORT_GUIDANCE = (
    "**Poll vs. WebSocket:** poll `GET /convert/{job_id}` as the primary "
    "transport. `ws://…/convert/{job_id}/ws` pushes the same status object on "
    "change, but on serverless deployments (e.g. Vercel Functions) an idle "
    "socket can be killed mid-job **and a paused instance only advances the "
    "job while a request is in flight** — so on any close before a terminal "
    "status (`succeeded`/`failed`), fall back to polling; do not build a "
    "WS-only client. Neither transport reports a percentage: the converters "
    "have no progress hook, so `logs` carries a handful of coarse, "
    "fixed-stage checkpoints."
)


class ErrorDetail(BaseModel):
    """FastAPI's standard error body, declared so error responses codegen."""

    detail: str


class ConversionJobStatus(BaseModel):
    """One conversion job as returned by the poll/list routes.

    The exact shape of `ConversionJob.to_dict()` (`jobs.py`) — declared here
    (not derived from the dataclass) so the OpenAPI stops being
    `additionalProperties: true` and clients can codegen against it.
    """

    id: str
    source_format: str = Field(
        description="A `SourceFormat` value for `/convert` jobs; `/ingest` "
        "jobs (same registry) carry a detected file suffix instead."
    )
    name: str
    display_name: str | None = Field(
        description="Human-readable title derived from the source document's "
        "own metadata (fallback: the request `name` / filename stem). Set "
        "once the job starts running."
    )
    status: JobStatus
    created_at: float
    started_at: float | None
    finished_at: float | None
    error: str | None = Field(description="Failure reason once `status` is `failed`.")
    logs: list[str] = Field(
        description="Coarse fixed-stage checkpoints, not progress — the "
        "conversion pipeline has no percentage hook."
    )
    last_log: str | None
    validation: dict[str, Any] | None = Field(
        description="Post-conversion corpus validation summary "
        "(`corpus`/`valid`/`stats`/`reasons`/`checks`) — set once the "
        "converted archive has been checked (issue #177); an invalid "
        "archive also fails the job with the top reasons in `error`."
    )
    result_filename: str = Field(
        description="The filename a client should persist the result under "
        "(always ends in `.corpus` for /convert jobs); matches the "
        "`Content-Disposition` on `/download`."
    )
    download_ready: bool


class ConversionJobList(BaseModel):
    """Page of the caller's jobs, most recent first."""

    jobs: list[ConversionJobStatus]
    total: int = Field(description="Jobs visible to the caller, ignoring pagination.")
    offset: int
    limit: int


class ConversionAccepted(BaseModel):
    """`202` body from `POST /convert`: where to watch the job from."""

    job_id: str
    status_url: str
    ws_url: str


def _claims(request: Request) -> dict[str, Any] | None:
    """The decoded JWT claims `AuthMiddleware` attached to this request.

    `None` if auth is currently disabled (`AUTH_REQUIRED=false`) -- see
    `corpora_py.auth`. Only ever reads `request.state`, never verifies
    anything itself: this router has no auth policy of its own (see this
    module's docstring).
    """
    return getattr(request.state, "user", None)


def _not_found_unless_visible(
    job: ConversionJob | None, request: Request
) -> ConversionJob:
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


def _resolve_corpus_path(name: str, job_id: str) -> tuple[Path, str]:
    """Pick the on-disk `.corpus` path and its exposed filename for one job.

    The stem is `_slugify(name)` (e.g. `"Summa Theologiae 1200 ENG"` ->
    `"summa-theologiae-1200-eng"`), falling back to the job id when `name`
    has no alphanumeric content. If a file with that name already exists in
    `_RESULTS_ROOT` (two jobs with the same `name` finishing close together,
    or a re-run of an idempotent job), a short uuid suffix is appended to
    keep the on-disk files unique -- the exposed `result_filename` tracks
    that suffix so a client echoing it back on download matches the actual
    archive. The filename always ends in `.corpus` (see issue #108).
    """
    _RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    filename = result_filename_for(name, SourceFormat.PLAIN, job_id=job_id)
    path = _RESULTS_ROOT / filename
    if path.exists():
        stem = _slugify(name) or _slugify(job_id) or job_id
        filename = f"{stem}-{uuid.uuid4().hex[:8]}{_CORPUS_SUFFIX}"
        path = _RESULTS_ROOT / filename
    return path, filename


# Display-name derivation moved to `conversion.py` (issue #188) so the
# `corpora` CLI shares it; these bindings keep this module's historical
# private names working for existing callers and tests.
_clean_filename_stem = clean_filename_stem
_extract_source_title = extract_source_title
_derive_display_name = derive_display_name


class ConversionValidationError(JobFailedError):
    """The converted archive failed post-conversion validation (issue #177).

    The message is client-facing by design (see `JobFailedError`): the top
    validation reasons are exactly what the submitter needs to see in
    `job.error`.
    """


def _validate_converted_corpus(archive: Path, job_id: str) -> None:
    """Run `validate_corpus_archive` over the freshly-built archive (#177).

    The summary is attached to the job either way (via
    `JobManager.set_validation`, so it rides the terminal status); an
    invalid archive raises `ConversionValidationError` so the job fails
    with the top reasons in `error` instead of shipping a broken corpus.
    The validator import stays lazy (inside `conversion.validate_archive`):
    `corpora_mcp` is a sibling workspace package that admin doesn't import
    at module load.
    """
    job_manager.log(job_id, "Validating converted corpus...")
    summary = validate_archive(archive)
    job_manager.set_validation(job_id, summary)
    if not summary.get("valid"):
        reasons = [str(r) for r in summary.get("reasons") or []]
        detail = "; ".join(reasons[:3]) or "corpus integrity checks failed"
        raise ConversionValidationError(
            f"Converted corpus failed validation: {detail}"
        )


def _run_conversion(
    *,
    source_path: Path,
    work_dir: Path,
    source_format: SourceFormat,
    name: str,
    description: str,
    job_id: str,
    category: CorpusCategory | None = None,
) -> Path:
    """Blocking pipeline: parse -> Text-Fabric -> .cfm -> .corpus.

    Runs on a `JobManager` worker thread -- never call this directly from an
    async endpoint. Always cleans up `work_dir` (the upload + intermediate
    `tf/` tree) on the way out, success or failure -- only the final
    `.corpus`, written to `_RESULTS_ROOT`, survives.

    The `display_name` (human-readable title from the source document's own
    metadata, falling back to the request `name` / filename stem -- see
    issue #109) is derived before the expensive TF walk so it's available on
    the running status, written into `manifest.name`, and slugified for the
    on-disk archive filename. The `job_manager.log()` calls bracketing each
    stage are coarse, fixed checkpoints, not real progress --
    `converter()` and `convert_to_corpus()` have no progress hook to report
    from mid-call (see `packages/admin/CLAUDE.md`'s "Known gaps"). They
    exist so a client watching `/convert/{id}/ws` sees *something* move
    during a multi-minute conversion instead of a status stuck on "running"
    with no other signal.
    """
    job = job_manager.get(job_id)
    try:
        return run_conversion(
            source_path=source_path,
            work_dir=work_dir,
            source_format=source_format,
            output_path_for=lambda display: _resolve_corpus_path(display, job_id)[0],
            name=name,
            description=description,
            category=category,
            author_sub=job.owner if job is not None else None,
            # Passed from this module's globals at call time so the test
            # seams (`monkeypatch.setattr(api_module, "convert_to_corpus")`,
            # `monkeypatch.setitem(api_module.CONVERTERS, ...)`) keep
            # working.
            converters=CONVERTERS,
            convert_fn=convert_to_corpus,
            # `job.error` round-trips to clients, so a converter message
            # naming any of these server-side paths keeps the sanitized
            # generic form instead of the verbatim passthrough (issue #184).
            private_paths=(
                str(work_dir),
                tempfile.gettempdir(),
                str(_RESULTS_ROOT),
            ),
            on_log=lambda message: job_manager.log(job_id, message),
            on_display_name=lambda display: job_manager.set_display_name(
                job_id, display
            ),
            on_validation=lambda summary: job_manager.set_validation(
                job_id, summary
            ),
        )
    except CorpusValidationError as exc:
        raise ConversionValidationError(str(exc)) from exc
    except ConversionError as exc:
        # `JobFailedError` is the one family whose message `JobManager._run`
        # exposes verbatim in `job.error` (issue #184).
        raise JobFailedError(str(exc)) from exc


@router.post(
    "",
    status_code=202,
    response_model=ConversionAccepted,
    responses={
        413: {
            "model": ErrorDetail,
            "description": f"Upload exceeds the "
            f"{_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.",
        },
        422: {
            "description": "Invalid upload filename, no converter registered "
            "for `source_format`, or the upload failed pre-conversion "
            "validation — in that last case `detail` is a report object "
            "(declared/detected format, `convertible`, `reasons`, `warnings`, "
            "and a `pdf` classification payload for PDF uploads) rather than "
            "a string.",
        },
        429: {
            "model": ErrorDetail,
            "description": "Job queue is full — retry after in-flight "
            "conversions finish.",
        },
        503: {
            "model": ErrorDetail,
            "description": "Shared job store is unconfigured or unavailable "
            "(`JOB_STORE=supabase`).",
        },
    },
    description=(
        "Upload a source document and start converting it in the background.\n\n"
        "Returns immediately (202) with a job id — the conversion itself has "
        "not finished yet and can take minutes for a large source (a full "
        "Bible, a multi-hundred-page EPUB). Uploads are capped at "
        f"{_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB (413 past that); a full "
        "job queue answers 429.\n\n" + _TRANSPORT_GUIDANCE
    ),
)
async def create_conversion(
    request: Request,
    file: UploadFile,
    source_format: SourceFormat = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    category: CorpusCategory | None = Form(
        default=None,
        description="Optional corpus category override "
        "(`document`/`book`/`religious`). Auto-detected from the parsed "
        "structure when omitted; an override requesting more structure than "
        "the source carries is downgraded with a warning on the job log "
        "(issue #176).",
    ),
) -> dict[str, str]:
    """Upload a source document and start converting it in the background.

    Returns immediately (202) with a job id -- the conversion itself has not
    finished yet. Poll `GET /convert/{job_id}` or open
    `ws://.../convert/{job_id}/ws` for status. (The /docs description on the
    decorator carries the client-facing limits + transport guidance --
    docstrings can't interpolate constants.)
    """
    if source_format not in CONVERTERS:
        raise HTTPException(
            status_code=422,
            detail=f"No converter registered for {source_format!r}. "
            f"Available: {sorted(f.value for f in CONVERTERS)}",
        )

    claims = _claims(request)
    owner = claims.get("sub") if claims else None

    # Minted up front (rather than reading `job.id` off the object
    # `job_manager.submit()` returns) so the `fn` closure below can call
    # `job_manager.log(job_id, ...)` from inside the worker thread --
    # referencing the not-yet-returned `job` object here would race the
    # executor, which can start running `fn` before `submit()` returns.
    job_id = str(uuid.uuid4())

    _WORK_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="job-", dir=str(_WORK_ROOT)))
    try:
        source_path = await _save_upload(file, work_dir / "source")

        # Pre-conversion gate (issue #173): sniff the real file type, refuse
        # anything that can only fail minutes later in the background job.
        report = validate_upload(source_path, source_format)
        if not report.convertible:
            raise HTTPException(status_code=422, detail=report.to_dict())

        try:
            job = job_manager.submit(
                job_id=job_id,
                source_format=source_format,
                name=name,
                owner=owner,
                fn=lambda: _run_conversion(
                    source_path=source_path,
                    work_dir=work_dir,
                    source_format=source_format,
                    name=name,
                    description=description,
                    job_id=job_id,
                    category=category,
                ),
            )
        except JobQueueFullError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except JobStoreNotConfiguredError as extra:
            raise HTTPException(status_code=503, detail=str(extra)) from extra
        except JobStoreError as extra:
            logger.exception("Job store failed to accept conversion %s", job_id)
            raise HTTPException(
                status_code=503, detail="Job store unavailable"
            ) from extra
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

    # Non-fatal upload findings (e.g. a mixed PDF's OCR-needing pages) go on
    # the job log so a client watching the job sees them without a second
    # response channel.
    for warning in report.warnings:
        job_manager.log(job.id, warning)

    logger.info("Queued conversion job %s (%s, %s)", job.id, source_format.value, name)
    return {
        "job_id": job.id,
        "status_url": f"/convert/{job.id}",
        "ws_url": f"/convert/{job.id}/ws",
    }


@router.get("", response_model=ConversionJobList)
async def list_conversions(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List the caller's conversion jobs (most recent first).

    When auth is enabled, returns only jobs owned by the caller (JWT ``sub``).
    When auth is disabled (``AUTH_REQUIRED=false``), returns all jobs —
    capped by ``limit`` so an anonymous deployment doesn't dump the full
    registry in one response. Lazy TTL reaping runs before listing so the
    count stays bounded (see ``JobManager.retention_seconds``).
    """
    claims = _claims(request)
    owner = claims.get("sub") if claims else None
    jobs, total = _store_op(
        lambda: job_manager.list_jobs(owner=owner, offset=offset, limit=limit)
    )
    return {
        "jobs": [j.to_dict() for j in jobs],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get(
    "/{job_id}",
    response_model=ConversionJobStatus,
    responses={
        404: {
            "model": ErrorDetail,
            "description": "Unknown job id — including a job that exists but "
            "belongs to a different submitter (deliberately the same "
            "response, so job ids can't be enumerated).",
        },
    },
    description=(
        "Poll the status of a conversion job. This is the primary status "
        "transport.\n\n" + _TRANSPORT_GUIDANCE
    ),
)
async def get_conversion(job_id: str, request: Request) -> dict[str, object]:
    """Poll the status of a conversion job.

    404s for a job that exists but belongs to a different submitter, same as
    an unknown id -- see `_not_found_unless_visible`.
    """
    job = _not_found_unless_visible(_store_op(lambda: job_manager.get(job_id)), request)
    return job.to_dict()


@router.get(
    "/{job_id}/download",
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "The finished `.corpus` archive; "
            "`Content-Disposition` carries `result_filename`.",
        },
        404: {"model": ErrorDetail, "description": "Unknown (or foreign) job id."},
        409: {
            "model": ErrorDetail,
            "description": "Job exists but is not `succeeded` yet — poll "
            "until `download_ready` is true.",
        },
    },
)
async def download_conversion(job_id: str, request: Request) -> FileResponse:
    """Download the finished `.corpus` archive for a succeeded job.

    `Content-Disposition` carries the job's `result_filename` (slugified
    from the user-supplied `name`, always ending in `.corpus`) rather than
    the on-disk `result_path.name` -- so the client's Save-As default is the
    human-readable library name, not the server-internal `job-<uuid>` id.
    `media_type` is `application/zip`: a `.corpus` archive is a zip, and an
    unknown type makes some browsers treat the download as raw bytes instead
    of a saveable file. 409 (not 404) until `download_ready`, matching the
    `GET /convert/{id}` contract.
    """
    archive = _resolve_succeeded(job_id, request)
    # `archive.name` is the slug of the display name (the human-readable
    # title from the source, see issue #109) plus any collision suffix --
    # matching what `to_dict()` exposes as `result_filename`, so the
    # Save-As default agrees with the library name the client already has.
    return FileResponse(
        archive,
        filename=archive.name,
        media_type="application/zip",
    )


# ── Job-scoped corpus detail ──────────────────────────────────────────────────
# `/convert/{job_id}/manifest|index|sections|content|nodes/{node}|versions`
# serve the same shapes as `/storage/{filename}/…` but read the conversion
# result straight off disk (no Hub). 409 unless the job succeeded; 404 for an
# unknown / foreign job id (same visibility rule as poll + download). Lets
# corpora-web explore a freshly-converted corpus without publishing it.


# Shared by every job-scoped detail route below: same 404 visibility rule as
# poll/download, 409 until the job succeeds (matching `/download`).
_JOB_DETAIL_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorDetail, "description": "Unknown (or foreign) job id."},
    409: {
        "model": ErrorDetail,
        "description": "Job exists but is not `succeeded` yet.",
    },
}


def _job_corpus_key(job_id: str) -> str:
    """Stable cache key for a job's result archive (``job-<id>.corpus``)."""
    return f"job-{job_id}"


def _store_op(fn):
    """Run a job-store call; misconfiguration / outage → HTTP 503."""
    try:
        return fn()
    except JobStoreNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JobStoreError as extra:
        logger.exception("Job store operation failed")
        raise HTTPException(
            status_code=503, detail="Job store unavailable"
        ) from extra


def _resolve_succeeded(job_id: str, request: Request) -> Path:
    """Return the result archive path for a succeeded, visible job or raise 404 / 409.

    Hydrates a remote `result_key` onto a local file when this instance
    did not run the conversion (issue #140). 409 until the job succeeded
    *and* the bytes are available.
    """
    job = _not_found_unless_visible(_store_op(lambda: job_manager.get(job_id)), request)
    if job.status != JobStatus.SUCCEEDED:
        raise HTTPException(
            status_code=409, detail=f"Job is {job.status.value}, not ready"
        )
    path = _store_op(lambda: job_manager.materialize(job))
    if path is None:
        raise HTTPException(
            status_code=409, detail=f"Job is {job.status.value}, not ready"
        )
    return path


@router.get("/{job_id}/manifest", responses=_JOB_DETAIL_RESPONSES)
async def get_job_manifest(job_id: str, request: Request) -> dict[str, Any]:
    """Return the converted archive's ``manifest.yml``."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_manifest(key))


@router.get("/{job_id}/index", responses=_JOB_DETAIL_RESPONSES)
async def get_job_index(job_id: str, request: Request) -> dict[str, Any]:
    """Return the converted archive's toc, section structure, and node-type stats."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_index(key))


@router.get("/{job_id}/sections", responses=_JOB_DETAIL_RESPONSES)
async def get_job_sections(
    job_id: str,
    request: Request,
    parent: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50),
) -> dict[str, Any]:
    """Paginated section children under ``parent`` (top-level if omitted)."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(
        lambda: get_sections(key, parent=parent, offset=offset, limit=limit)
    )


@router.get("/{job_id}/content", responses=_JOB_DETAIL_RESPONSES)
async def get_job_content(
    job_id: str,
    request: Request,
    ref: str | None = Query(default=None),
    fmt: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50),
) -> dict[str, Any]:
    """Return paginated passages under ``ref`` (or the whole corpus if omitted)."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(
        lambda: get_content(key, ref=ref, fmt=fmt, offset=offset, limit=limit)
    )


@router.get("/{job_id}/nodes/{node}", responses=_JOB_DETAIL_RESPONSES)
async def get_job_node(
    job_id: str, node: int, request: Request
) -> dict[str, Any]:
    """Inspect one graph node in the converted archive."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_node(key, node))


@router.get("/{job_id}/versions", responses=_JOB_DETAIL_RESPONSES)
async def get_job_versions(job_id: str, request: Request) -> dict[str, Any]:
    """Return the converted archive's version timeline."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_versions(key))


@router.patch("/{job_id}/manifest", responses=_JOB_DETAIL_RESPONSES)
async def patch_job_manifest(
    job_id: str, request: Request, payload: ManifestUpdate
) -> dict[str, Any]:
    """Patch the converted archive's manifest and bump ``v1.N`` (issue #149).

    Job-scoped writes stay available when Hub storage is read-only.
    """
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    updates = payload.model_dump(exclude_unset=True)
    return await _run_detail(lambda: update_manifest(key, updates))


@router.patch("/{job_id}/nodes/{node}", responses=_JOB_DETAIL_RESPONSES)
async def patch_job_node(
    job_id: str, node: int, request: Request, payload: NodeAnnotation
) -> dict[str, Any]:
    """Annotate a node in the converted archive and bump ``v1.N`` (issue #149)."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    updates = payload.model_dump(exclude_unset=True)
    return await _run_detail(lambda: annotate_node(key, node, **updates))


class RestoreBody(BaseModel):
    """Restore HEAD from a stored snapshot (issue #148)."""

    version_id: str = Field(min_length=1)


@router.post(
    "/{job_id}/restore",
    responses={
        **_JOB_DETAIL_RESPONSES,
        404: {
            "model": ErrorDetail,
            "description": "Unknown job, version, or missing snapshot.",
        },
    },
)
async def restore_job_corpus(
    job_id: str, request: Request, payload: RestoreBody
) -> dict[str, Any]:
    """Copy a stored snapshot over HEAD and append a restore history row.

    Job-scoped only — Hub storage restore stays 403/501. Not a git checkout.
    """
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    versions = (await _run_detail(lambda: get_versions(key)))["versions"]
    needle = payload.version_id.strip()
    row = _find_version_row(versions, needle)
    if row.get("current"):
        raise HTTPException(
            status_code=409, detail=f"{needle} is already the current version"
        )
    label = str(row.get("label") or needle)
    snapshot = _materialize_version(job_id, label, row)

    title = f"Restored {label}"
    return await _run_detail(
        lambda: restore_from_snapshot(key, snapshot, title=title)
    )


def _find_version_row(
    versions: list[dict[str, Any]], needle: str
) -> dict[str, Any]:
    """The history row whose ``id`` or ``label`` matches, or 404."""
    row = next(
        (
            item
            for item in versions
            if str(item.get("id") or "") == needle
            or str(item.get("label") or "") == needle
        ),
        None,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown version {needle!r}")
    return row


def _materialize_version(job_id: str, label: str, row: dict[str, Any]) -> Path:
    """A local archive path for one history row's snapshot, or 404/503."""
    snap_key = row.get("snapshot_key") or snapshot_key_for(job_id, label)
    try:
        return job_manager.materialize_snapshot(job_id, snap_key or "")
    except SnapshotMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobStoreNotConfiguredError as extra:
        raise HTTPException(status_code=503, detail=str(extra)) from extra
    except JobStoreError as extra:
        logger.exception("Snapshot fetch failed for job %s", job_id)
        raise HTTPException(
            status_code=503, detail="Job store unavailable"
        ) from extra


@router.get(
    "/{job_id}/diff",
    responses={
        **_JOB_DETAIL_RESPONSES,
        404: {
            "model": ErrorDetail,
            "description": "Unknown job, version, or missing snapshot.",
        },
    },
)
async def diff_job_versions(
    job_id: str,
    request: Request,
    from_version: str = Query(alias="from", min_length=1),
    to_version: str = Query(alias="to", min_length=1),
) -> dict[str, Any]:
    """Path-level diff between two versions of the converted archive (issue #151).

    ``from``/``to`` accept a history row's ``id`` or ``label``; the row
    marked ``current`` diffs against HEAD, any other resolves its stored
    snapshot. The diff lists member paths that were added, removed, or
    modified (size + CRC comparison) — no ``.tf`` content is dumped.
    Read-only: nothing is bumped, snapshotted, or republished.
    """
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    versions = (await _run_detail(lambda: get_versions(key)))["versions"]

    sides: list[tuple[dict[str, Any], Path]] = []
    for needle in (from_version.strip(), to_version.strip()):
        row = _find_version_row(versions, needle)
        if row.get("current"):
            sides.append((row, archive))
        else:
            label = str(row.get("label") or needle)
            sides.append((row, _materialize_version(job_id, label, row)))

    (from_row, before), (to_row, after) = sides
    files = await _run_detail(lambda: diff_archives(before, after))
    return {
        "from": {"id": from_row.get("id"), "label": from_row.get("label")},
        "to": {"id": to_row.get("id"), "label": to_row.get("label")},
        "files": files,
    }
