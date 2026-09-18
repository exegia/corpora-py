"""Authorized read-only curation over a private, per-call archive snapshot.

`corpus` is an archive ID in the configured store or `job:<UUID>` for an
owned conversion. Never fall back to the global CorpusManager or the shared
corpus-detail cache: those are not access-control decisions.
"""

from __future__ import annotations

import hmac
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import yaml
from admin.services import jobs, storage
from admin.services.corpus_detail import _safe_extract
from common.utils.config import settings
from common.utils.request_context import current_owner

from .schemas import ErrorInfo, NodeScope, ValidateResponse
from .scope import scope_content_hash, scope_nodes
from .validation import FeatureType, validate_nodes

_ARCHIVE_ID = re.compile(r"^[\w][\w .-]*$", re.UNICODE)


class CurationError(Exception):
    def __init__(self, status: int, error: ErrorInfo | str):
        self.status = status
        self.body = (
            error.model_dump(mode="json") if isinstance(error, ErrorInfo) else {"detail": error}
        )
        super().__init__(str(self.body))


def _archive(corpus: str, destination: Path) -> Path:
    owner = current_owner.get()
    if settings.auth_required and not owner:
        raise CurationError(
            403, ErrorInfo(code="forbidden", reason="Verified identity required", retryable=False)
        )
    if corpus.startswith("draft:"):
        from .drafts import download_to
        from .wal_sqlite import JournalUnavailableError

        path = destination / "snapshot.corpus"
        try:
            download_to(corpus[6:], path)
        except JournalUnavailableError as exc:
            raise CurationError(503, "Registered draft unavailable") from exc
        return path
    if settings.ai_mutations_enabled and owner:
        from .mutations import get_storage
        from .wal_sqlite import JournalUnavailableError

        hosted = get_storage()
        try:
            head = hosted.resolve(owner, corpus)
        except CurationError as exc:
            if exc.status != 404:
                raise
        except JournalUnavailableError as exc:
            raise CurationError(503, "Draft registry unavailable") from exc
        else:
            path = destination / "snapshot.corpus"
            try:
                hosted.download(head, path)
            except JournalUnavailableError as exc:
                raise CurationError(503, "Registered draft unavailable") from exc
            return path
    if corpus.startswith("job:"):
        try:
            job_id = str(UUID(corpus[4:]))
        except ValueError as exc:
            raise CurationError(422, "Expected job:<UUID>") from exc
        job = jobs.job_manager.get(job_id)
        if job is None or (owner is not None and job.owner != owner):
            raise CurationError(404, "Corpus not found")
        if job.status is not jobs.JobStatus.SUCCEEDED:
            raise CurationError(409, "Conversion is not ready")
        result = jobs.job_manager.materialize(job)
        if result is None:
            raise CurationError(409, "Conversion result is not available")
        path = destination / "snapshot.corpus"
        shutil.copyfile(result, path)
        return path
    if not _ARCHIVE_ID.fullmatch(corpus) or corpus != corpus.strip():
        raise CurationError(422, "Expected a flat corpus archive ID, not a path or URL")
    # Supabase storage prefixes with the verified current_owner. Hub storage
    # is the deployment's explicitly shared publishing library. Both apply
    # their normal read policy. Download directly to avoid local job aliases
    # or previously cached APIs bypassing the storage boundary.
    return storage.corpus_storage.download(corpus, dest_dir=destination)


def _requirements(api: Any) -> dict[str, dict[str, FeatureType]]:
    """Only section labels are universally required by otext's own schema."""
    types = tuple(api.T.sectionTypes)
    features = tuple(api.T.sectionFeats)
    value_types = tuple(api.T.sectionFeatureTypes)
    if len(types) != len(features) or len(features) != len(value_types):
        raise CurationError(422, "Corpus section schema is inconsistent")
    requirements: dict[str, dict[str, FeatureType]] = {}
    # T exposes normalized types for both TF and mmap-backed CF loads; raw
    # feature metadata uses valueType in TF but value_type in a CFM archive.
    for kind, name, value_type in zip(types, features, value_types, strict=True):
        if value_type not in ("int", "str"):
            raise CurationError(422, "Corpus section feature has an unsupported value type")
        requirements.setdefault(kind, {})[name] = cast(FeatureType, value_type)
    return requirements


def validate_scope(scope: NodeScope) -> ValidateResponse:
    """Authorize before loading; read manifest and nodes from the same snapshot."""
    try:
        with tempfile.TemporaryDirectory(prefix="corpora-ai-validation-") as temporary:
            root = Path(temporary)
            archive = _archive(scope.corpus, root)
            extracted = root / "extracted"
            extracted.mkdir()
            with zipfile.ZipFile(archive) as zf:
                try:
                    _safe_extract(zf, extracted)
                except storage.StorageError as exc:
                    raise CurationError(422, "Corpus archive contains an unsafe path") from exc
            manifest = yaml.safe_load((extracted / "manifest.yml").read_text())
            if not isinstance(manifest, dict) or not manifest.get("version"):
                raise CurationError(422, "Corpus manifest has no version")
            version = str(manifest["version"])
            if scope.version.removeprefix("v") != version.removeprefix("v"):
                raise CurationError(
                    409,
                    ErrorInfo(
                        code="stale",
                        reason="Corpus version has changed",
                        retryable=False,
                        current_version=version,
                    ),
                )
            from cfabric import Fabric

            api = Fabric(locations=str(extracted / "corpora"), silent="deep").loadAll(silent="deep")
            if api is False or api is None:
                raise CurationError(422, "Corpus dataset could not be loaded")
            nodes = scope_nodes(api, scope)
            if scope.content_hash is not None and not hmac.compare_digest(
                scope.content_hash.encode("utf-8"), scope_content_hash(api, nodes).encode("ascii")
            ):
                raise CurationError(
                    409,
                    ErrorInfo(
                        code="stale",
                        reason="Scoped text has changed",
                        retryable=False,
                        current_version=version,
                    ),
                )
            return validate_nodes(
                api,
                corpus=scope.corpus,
                version=version,
                nodes=nodes,
                required_features=_requirements(api),
            )
    except storage.CorpusNotFoundError as exc:
        raise CurationError(404, "Corpus not found") from exc
    except (storage.StorageError, jobs.JobStoreError) as exc:
        # Upstream exceptions may contain URLs, credentials, paths, or bodies.
        raise CurationError(503, "Corpus storage is unavailable") from exc
    except (OSError, zipfile.BadZipFile, yaml.YAMLError) as exc:
        raise CurationError(422, "Corpus archive is unreadable") from exc
    except ValueError as exc:
        raise CurationError(422, str(exc)) from exc
