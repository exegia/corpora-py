"""Provision and read private working copies of owned conversion results."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import yaml
from admin.services import corpus_detail, jobs
from admin.services import storage as legacy_storage
from common.utils.config import settings
from common.utils.request_context import current_owner

from . import mutations
from .archive_editor import _load, digest
from .schemas import DraftInfo, DraftListResponse, DraftReadResponse
from .service import CurationError
from .wal_sqlite import JournalUnavailableError
from .wal_supabase import DraftHead, HostedStorage, _parse, _uuid


def _storage() -> tuple[str, HostedStorage]:
    owner = current_owner.get()
    if not owner:
        raise CurationError(403, "Verified identity required for working drafts")
    if settings.ai_store != "supabase":
        raise CurationError(503, "Working drafts require hosted storage")
    return _uuid(owner), mutations.get_storage()


def _require_provisioning(storage: HostedStorage, owner: str) -> None:
    try:
        capability = storage.rpc("capabilities", owner, {})
    except CurationError as exc:
        raise JournalUnavailableError("Draft database migration is unavailable") from exc
    if not isinstance(capability, dict) or capability.get("draft_api") != 1:
        raise JournalUnavailableError("Draft database migration is unavailable")


def _info(head: DraftHead) -> DraftInfo:
    return DraftInfo(
        id=head.document_id,
        corpus=head.corpus,
        revision=head.revision,
        digest=head.digest,
        version=head.version,
        state=head.state,
        archive_url=f"/ai/drafts/{head.document_id}/archive",
    )


def _head(storage: HostedStorage, owner: str, draft_id: str) -> DraftHead:
    draft_id = _uuid(draft_id)
    head = storage.resolve(owner, "draft:" + draft_id)
    if head.document_id != draft_id:
        raise JournalUnavailableError("Invalid draft binding")
    return head


def get(draft_id: str) -> DraftInfo:
    owner, storage = _storage()
    return _info(_head(storage, owner, draft_id))


def create(job_id: str) -> DraftInfo:
    owner, storage, _ = mutations._context()
    if settings.hf_read_only:
        raise CurationError(423, "Working draft creation is disabled on this read-only deployment")
    _require_provisioning(storage, owner)
    job_id = _uuid(job_id)
    try:
        job = jobs.job_manager.get(job_id)
        # Anonymous legacy jobs and global document IDs never establish rights.
        if job is None or job.owner != owner:
            raise CurationError(404, "Owned conversion job not found")
        if job.status is not jobs.JobStatus.SUCCEEDED:
            raise CurationError(409, "Conversion is not ready")
        document_id = str(uuid5(NAMESPACE_URL, json.dumps(["ai-draft", owner, job_id])))
        try:
            return _info(_head(storage, owner, document_id))
        except CurationError as exc:
            if exc.status != 404:
                raise
        source = jobs.job_manager.materialize(job)
        if source is None:
            raise CurationError(409, "Conversion result is unavailable")
        with tempfile.TemporaryDirectory(prefix="ai-provision-") as temporary:
            root = Path(temporary)
            archive = root / "source.corpus"
            shutil.copyfile(source, archive)
            extracted = root / "extracted"
            extracted.mkdir()
            with zipfile.ZipFile(archive) as packed:
                try:
                    corpus_detail._safe_extract(packed, extracted)
                except legacy_storage.StorageError as exc:
                    raise CurationError(422, "Conversion archive contains an unsafe path") from exc
            _, manifest = _load(extracted)
            version = str(manifest["version"])
            if not re.fullmatch(r"v?[0-9]+\.[0-9]+", version):
                raise CurationError(422, "Working drafts require a major.minor archive version")
            revision = str(uuid4())
            head = DraftHead(
                document_id=document_id,
                owner=owner,
                corpus="draft:" + document_id,
                bucket="corpus-ai-drafts",
                object_key=f"{owner}/ai/{document_id}/{revision}.corpus",
                revision=revision,
                digest=digest(archive),
                version=version,
            )
            storage.stage(head, revision, archive, head.digest)
            # The single transaction inserts a PRIVATE document and its binding.
            # Concurrent initializers return the first binding without replacing it.
            value = storage.rpc(
                "provision",
                owner,
                {
                    **head.model_dump(exclude={"owner", "state"}),
                    "job_id": job_id,
                    "name": str(manifest.get("name") or job.display_name or job.name)[:512],
                },
            )
            result = _parse(DraftHead, value)
            if (
                result.owner != owner
                or result.document_id != document_id
                or result.corpus != head.corpus
            ):
                raise JournalUnavailableError("Invalid draft binding")
            return _info(result)
    except (jobs.JobStoreError, legacy_storage.StorageError) as exc:
        raise CurationError(503, "Conversion storage unavailable") from exc
    except (OSError, zipfile.BadZipFile, yaml.YAMLError) as exc:
        raise CurationError(422, "Conversion archive is unreadable") from exc


def list_drafts(limit: int = 50, offset: int = 0) -> DraftListResponse:
    owner, storage = _storage()
    _require_provisioning(storage, owner)
    if not 1 <= limit <= 100 or offset < 0:
        raise CurationError(422, "Invalid draft pagination")
    rows = storage.rpc("drafts", owner, {"limit": limit + 1, "offset": offset})
    if not isinstance(rows, list):
        raise JournalUnavailableError("Draft storage unavailable")
    heads = [_parse(DraftHead, row) for row in rows]
    if any(h.owner != owner or h.corpus != "draft:" + h.document_id for h in heads):
        raise JournalUnavailableError("Invalid draft binding")
    return DraftListResponse(
        drafts=[_info(h) for h in heads[:limit]],
        next_offset=offset + limit if len(heads) > limit else None,
    )


def download_to(draft_id: str, path: Path) -> DraftInfo:
    owner, storage = _storage()
    head = _head(storage, owner, draft_id)
    storage.download(head, path)
    return _info(head)


def read(draft_id: str, view: str, **kwargs: Any) -> DraftReadResponse:
    if view == "node" and (not isinstance(kwargs.get("node"), int) or kwargs["node"] < 1):
        raise CurationError(422, "Expected a positive node ID")
    try:
        with tempfile.TemporaryDirectory(prefix="ai-read-") as temporary:
            archive = Path(temporary) / "draft.corpus"
            info = download_to(draft_id, archive)
            data = corpus_detail.read_archive(archive, view, **kwargs)
            return DraftReadResponse(draft=info, data=data)
    except legacy_storage.CorpusNotFoundError as exc:
        raise CurationError(404, "Draft node or section not found") from exc
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        yaml.YAMLError,
        legacy_storage.StorageError,
    ) as exc:
        raise CurationError(422, "Working draft is unreadable") from exc


def export(draft_id: str) -> tuple[tempfile.TemporaryDirectory, DraftInfo]:
    temporary = tempfile.TemporaryDirectory(prefix="ai-export-")
    try:
        info = download_to(draft_id, Path(temporary.name) / "draft.corpus")
        return temporary, info
    except BaseException:
        temporary.cleanup()
        raise
