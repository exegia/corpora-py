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
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from ..converters import CONVERTERS
from ..converters.convert_to_corpus import convert_to_corpus
from ..parsers import PARSERS
from ..parsers.schema import SourceFormat
from .corpus_detail import (
    get_content,
    get_index,
    get_manifest,
    get_node,
    get_sections,
    get_versions,
    register_local_archive,
)
from .corpus_detail_api import _run as _run_detail
from .jobs import (
    _CORPUS_SUFFIX,
    ConversionJob,
    JobQueueFullError,
    JobStatus,
    _slugify,
    job_manager,
    result_filename_for,
)

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


def _clean_filename_stem(filename: str) -> str:
    """Turn an upload filename into a human-readable fallback title.

    Strips the extension, replaces ``-`` and ``_`` with spaces, collapses
    repeated whitespace, and strips. ``"summa-theologia-1200-ENG.xml"`` ->
    ``"summa theologia 1200 ENG"``. This is the last-resort fallback (see
    `_derive_display_name`) for when the source has no extractable title and
    the client supplied no `name` -- not a title-caser, so the original
    letter casing survives untouched.
    """
    stem = Path(filename).stem
    return re.sub(r"\s+", " ", stem.replace("-", " ").replace("_", " ")).strip()


def _extract_source_title(
    source_format: SourceFormat, source_path: Path
) -> str | None:
    """Read the source document's own title, if a parser knows how.

    Uses the format parser's lightweight ``parse_metadata`` (headers only --
    TEI ``teiHeader``, PDF ``info``, HTML ``<title>``, EPUB ``dc:title``),
    not the full parse, so this is cheap to run before the expensive TF
    walk. Returns ``None`` for formats without a parser (``tf_zip`` --
    already a dataset, no source metadata; ``tei_zip`` -- multiple
    documents, no single title), so the caller falls back to the request
    ``name`` / filename stem (see issue #109).
    """
    parser = PARSERS.get(source_format)
    if parser is None:
        return None
    try:
        return parser.parse_metadata(str(source_path)).title
    except Exception:
        logger.warning(
            "Metadata extraction failed for %s (%s) -- falling back to "
            "request name",
            source_path.name,
            source_format.value,
            exc_info=True,
        )
        return None


def _derive_display_name(
    *,
    source_format: SourceFormat,
    source_path: Path,
    name: str,
) -> str:
    """Pick the human-readable title that becomes ``manifest.name``.

    Priority (see issue #109):
    1. The source document's own title (TEI ``titleStmt``, PDF
       ``info.title``, HTML ``<title>``, EPUB ``dc:title``) -- a person would
       read this.
    2. The request ``name`` (whatever the client sent -- may already be
       human-readable).
    3. A cleaned upload filename stem (spaces, not kebab).

    Never returns an empty string: the filename stem is the final stop and
    always has at least the stem of the uploaded file.
    """
    source_title = _extract_source_title(source_format, source_path)
    if source_title and source_title.strip():
        return source_title.strip()
    if name and name.strip():
        return name.strip()
    return _clean_filename_stem(source_path.name) or name


def _run_conversion(
    *,
    source_path: Path,
    work_dir: Path,
    source_format: SourceFormat,
    name: str,
    description: str,
    job_id: str,
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
    display_name = _derive_display_name(
        source_format=source_format, source_path=source_path, name=name
    )
    job_manager.set_display_name(job_id, display_name)
    try:
        if source_format == SourceFormat.TF_ZIP:
            job_manager.log(
                job_id, "Inspecting ZIP and importing Text-Fabric dataset..."
            )
        elif source_format == SourceFormat.TEI_ZIP:
            job_manager.log(
                job_id,
                "Extracting TEI documents from ZIP and building Text-Fabric dataset...",
            )
        else:
            job_manager.log(
                job_id,
                f"Parsing {source_format.value} source and building Text-Fabric dataset...",
            )
        converter = CONVERTERS[source_format]
        tf_dir = work_dir / "tf"
        converter(str(source_path), tf_dir)

        job_manager.log(
            job_id,
            "Text-Fabric dataset ready. Compiling cache and packaging .corpus archive...",
        )
        corpus_path, _filename = _resolve_corpus_path(display_name, job_id)
        result = convert_to_corpus(
            tf_dir, corpus_path, name=display_name, description=description
        )

        job_manager.log(job_id, "Conversion complete.")
        return result
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


@router.get("")
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
    jobs, total = job_manager.list_jobs(owner=owner, offset=offset, limit=limit)
    return {
        "jobs": [j.to_dict() for j in jobs],
        "total": total,
        "offset": offset,
        "limit": limit,
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
    job = _not_found_unless_visible(job_manager.get(job_id), request)
    if job.status != JobStatus.SUCCEEDED or job.result_path is None:
        raise HTTPException(
            status_code=409, detail=f"Job is {job.status.value}, not ready"
        )
    # `result_path.name` is the slug of the display name (the human-readable
    # title from the source, see issue #109) plus any collision suffix --
    # matching what `to_dict()` exposes as `result_filename`, so the
    # Save-As default agrees with the library name the client already has.
    return FileResponse(
        job.result_path,
        filename=job.result_path.name,
        media_type="application/zip",
    )


# ── Job-scoped corpus detail ──────────────────────────────────────────────────
# `/convert/{job_id}/manifest|index|sections|content|nodes/{node}|versions`
# serve the same shapes as `/storage/{filename}/…` but read the conversion
# result straight off disk (no Hub). 409 unless the job succeeded; 404 for an
# unknown / foreign job id (same visibility rule as poll + download). Lets
# corpora-web explore a freshly-converted corpus without publishing it.


def _job_corpus_key(job_id: str) -> str:
    """Stable cache key for a job's result archive (``job-<id>.corpus``)."""
    return f"job-{job_id}"


def _resolve_succeeded(job_id: str, request: Request) -> Path:
    """Return the result archive path for a succeeded, visible job or raise 404 / 409."""
    job = _not_found_unless_visible(job_manager.get(job_id), request)
    if job.status != JobStatus.SUCCEEDED or job.result_path is None:
        raise HTTPException(
            status_code=409, detail=f"Job is {job.status.value}, not ready"
        )
    return job.result_path


@router.get("/{job_id}/manifest")
async def get_job_manifest(job_id: str, request: Request) -> dict[str, Any]:
    """Return the converted archive's ``manifest.yml``."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_manifest(key))


@router.get("/{job_id}/index")
async def get_job_index(job_id: str, request: Request) -> dict[str, Any]:
    """Return the converted archive's toc, section structure, and node-type stats."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_index(key))


@router.get("/{job_id}/sections")
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


@router.get("/{job_id}/content")
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


@router.get("/{job_id}/nodes/{node}")
async def get_job_node(
    job_id: str, node: int, request: Request
) -> dict[str, Any]:
    """Inspect one graph node in the converted archive."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_node(key, node))


@router.get("/{job_id}/versions")
async def get_job_versions(job_id: str, request: Request) -> dict[str, Any]:
    """Return the converted archive's version timeline."""
    archive = _resolve_succeeded(job_id, request)
    key = register_local_archive(_job_corpus_key(job_id), archive)
    return await _run_detail(lambda: get_versions(key))
