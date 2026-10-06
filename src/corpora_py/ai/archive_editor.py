"""Stage typed feature edits in private archive copies; never overwrite HEAD."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from admin.converters.convert_to_corpus import _build_toc
from admin.services.corpus_detail import _safe_extract
from admin.services.storage import StorageError
from cfabric import Fabric

from .schemas import Suggestion, SuggestionKind
from .scope import scope_content_hash, scope_nodes
from .service import CurationError
from .wal import Evidence, Intent, Plan, _operation_id, _validate_plan
from .wal_supabase import DraftHead, HostedStorage


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()


def _load(root: Path) -> tuple[Any, dict]:
    manifest = yaml.safe_load((root / "manifest.yml").read_text())
    if not isinstance(manifest, dict) or not manifest.get("version"):
        raise CurationError(422, "Archive manifest has no version")
    # Source files are required so cache regeneration cannot silently discard
    # a CFM-only feature. Unrecognized formats are read-only for this adapter.
    corpus = root / "corpora"
    if not (corpus / "otype.tf").is_file() or not (corpus / "oslots.tf").is_file():
        raise CurationError(422, "Feature editing requires retained Text-Fabric sources")
    api = Fabric(locations=str(corpus), silent="deep").loadAll(silent="deep")
    if api is None or isinstance(api, bool):
        raise CurationError(422, "Corpus features could not be loaded")
    for feature in (*api.Fall(), *api.Eall(), "otext"):
        if not (corpus / (feature + ".tf")).is_file():
            raise CurationError(422, "Feature editing requires complete Text-Fabric sources")
    return api, manifest


def _values(api: Any, suggestion: Suggestion) -> dict[str, str | None]:
    if suggestion.target_node not in scope_nodes(api, suggestion.scope):
        raise CurationError(422, "Suggestion target is outside its pinned scope")
    result = {}
    for name in api.Fall():
        value = api.Fs(name).v(suggestion.target_node)
        result[name] = None if value is None else str(value)
    return result


def _untouched_hash(api: Any, fields: set[str], target: int) -> str:
    """Detect stale caches or rebuild drift outside the exact edited values."""
    checksum = hashlib.sha256()
    for name in sorted(api.Fall()):
        for node, value in sorted(api.Fs(name).items()):
            if name in fields and node == target:
                continue
            checksum.update(
                json.dumps(["node", name, int(node), str(value)], ensure_ascii=False).encode()
            )
            checksum.update(b"\n")
    for name in sorted(api.Eall()):
        for node, linked in sorted(api.Es(name).items()):
            destinations = (
                sorted((int(n), str(value)) for n, value in linked.items())
                if isinstance(linked, dict)
                else sorted(int(n) for n in linked)
            )
            checksum.update(
                json.dumps(["edge", name, int(node), destinations], ensure_ascii=False).encode()
            )
            checksum.update(b"\n")
    return checksum.hexdigest()


def _evidence(api: Any, manifest: dict, head: DraftHead, suggestion: Suggestion) -> Evidence:
    if str(manifest["version"]).removeprefix("v") != head.version.removeprefix("v"):
        raise CurationError(409, "Draft manifest and registered version differ")
    return Evidence(
        revision=head.revision,
        digest=head.digest,
        version=head.version,
        content_hash=scope_content_hash(api, scope_nodes(api, suggestion.scope)),
        values=_values(api, suggestion),
    )


def _extract(archive: Path, root: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        _safe_extract(source, root)


def inspect_archive(archive: Path, head: DraftHead, suggestion: Suggestion) -> Evidence:
    try:
        if digest(archive) != head.digest:
            raise CurationError(409, "Downloaded draft digest mismatch")
        with tempfile.TemporaryDirectory(prefix="ai-inspect-") as temporary:
            root = Path(temporary)
            _extract(archive, root)
            api, manifest = _load(root)
            return _evidence(api, manifest, head, suggestion)
    except (OSError, ValueError, zipfile.BadZipFile, yaml.YAMLError, StorageError) as exc:
        raise CurationError(422, "Corpus archive cannot be inspected") from exc


def edit_archive(archive: Path, output: Path, head: DraftHead, suggestion: Suggestion) -> Plan:
    """Preserve all unrelated archive members; return exact before/after proof.

    Only existing typed node features may change. Slot text and graph topology
    remain source/walker responsibilities. A fresh cache and TOC are mandatory.
    """
    try:
        if archive.resolve() == output.resolve():
            raise CurationError(422, "Staging output must differ from the source archive")
        if digest(archive) != head.digest:
            raise CurationError(409, "Downloaded draft digest mismatch")
        with tempfile.TemporaryDirectory(prefix="ai-edit-") as temporary:
            root = Path(temporary)
            _extract(archive, root)
            api, manifest = _load(root)
            before = _evidence(api, manifest, head, suggestion)
            if suggestion.kind in (SuggestionKind.boundary, SuggestionKind.text):
                raise CurationError(
                    422, "Boundary and source-text repairs require the source/walker workflow"
                )
            fields = [row.field for row in suggestion.diff]
            if len(set(fields)) != len(fields):
                raise CurationError(422, "Duplicate feature in change")
            # All declared render-format dependencies are protected, not only a
            # literal feature named text. This also prevents forged kind labels.
            otext = (root / "corpora" / "otext.tf").read_text()
            rendered = set()
            for line in otext.splitlines():
                if line.startswith("@fmt:"):
                    for token in re.findall(r"\{([^}]+)\}", line):
                        rendered.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", token))
            untouched = _untouched_hash(api, set(fields), suggestion.target_node)
            changes: dict[str, dict[int, str | int]] = {}
            metadata = {}
            for row in suggestion.diff:
                name = row.field
                if (
                    not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                    or name in {"otype", "oslots", "otext"}
                    or name in rendered
                    or name not in api.Fall()
                ):
                    raise CurationError(422, "Feature is not editable")
                if before.values.get(name) != row.old or row.old == row.new:
                    raise CurationError(409, "Displaced feature value does not match")
                source = root / "corpora" / (name + ".tf")
                header = source.read_text().split("\n\n", 1)[0]
                kind = re.search(r"^@valueType=(str|int)$", header, re.M)
                if kind is None:
                    raise CurationError(422, "Feature has no supported value type")
                values = dict(api.Fs(name).items())
                if row.new is None:
                    required = dict(zip(api.T.sectionTypes, api.T.sectionFeats, strict=True))
                    if name == required.get(api.F.otype.v(suggestion.target_node)):
                        raise CurationError(422, "A required section label cannot be removed")
                    values.pop(suggestion.target_node, None)
                elif kind[1] == "int":
                    if not re.fullmatch(r"-?(0|[1-9][0-9]*)", row.new):
                        raise CurationError(422, "Integer feature requires a canonical integer")
                    number = int(row.new)
                    if not -(2**63) <= number < 2**63:
                        raise CurationError(422, "Integer feature exceeds the supported range")
                    values[suggestion.target_node] = number
                else:
                    if "\x00" in row.new:
                        raise CurationError(422, "Feature value contains a null byte")
                    values[suggestion.target_node] = row.new
                changes[name] = values
                metadata[name] = dict(api.TF.features[name].metaData)
                metadata[name]["valueType"] = kind[1]
            match = re.fullmatch(r"v?(\d+)\.(\d+)", head.version)
            if not match:
                raise CurationError(422, "Draft version must use major.minor notation")
            version = f"v{match[1]}.{int(match[2]) + 1}"
            revision = str(uuid4())
            expected = dict(before.values)
            expected.update({r.field: r.new for r in suggestion.diff})
            # Validate stale version/hash before writing even the private copy.
            _validate_plan(
                suggestion,
                Plan(
                    before=before,
                    after=Evidence(
                        revision=revision,
                        digest="staged",
                        version=version,
                        content_hash=before.content_hash,
                        values=expected,
                    ),
                ),
            )
            if not Fabric(locations=str(root / "corpora"), silent="deep").save(
                nodeFeatures=changes,
                metaData=metadata,
                location=str(root / "corpora"),
                silent="deep",
            ):
                raise CurationError(422, "Feature serialization failed")
            # Never ship stale compiled data after modifying the source features.
            shutil.rmtree(root / "corpora" / ".cfm", ignore_errors=False)
            if (root / "corpora" / ".tf").exists():
                shutil.rmtree(root / "corpora" / ".tf")
            manifest["version"] = version
            (root / "manifest.yml").write_text(yaml.safe_dump(manifest, sort_keys=False))
            old_toc = yaml.safe_load((root / "toc.yml").read_text())
            if not isinstance(old_toc, dict):
                raise CurationError(422, "Invalid archive table of contents")
            toc = _build_toc(
                uid=str(old_toc.get("uid", "")),
                version=version,
                corpus_id=str(manifest.get("uid", "")),
                corpora_dir=root / "corpora",
                publisher_id=str(old_toc.get("publisherId", "")),
                author_ids=old_toc.get("authorId", []),
            )
            (root / "toc.yml").write_text(
                yaml.safe_dump(
                    {
                        **old_toc,
                        **{
                            key: toc[key]
                            for key in (
                                "version",
                                "has_sections",
                                "has_features",
                                "has_nodes",
                                "files",
                                "total_file_count",
                                "total_file_size",
                            )
                        },
                    },
                    sort_keys=False,
                )
            )
            history_path = root / "history.yml"
            history = yaml.safe_load(history_path.read_text())
            if not isinstance(history, dict) or not isinstance(history.get("versions"), list):
                raise CurationError(422, "Archive version history is missing or invalid")
            if any(not isinstance(entry, dict) for entry in history["versions"]):
                raise CurationError(422, "Archive version history contains invalid entries")
            if any(
                str(entry.get("label", "")).removeprefix("v") == version.removeprefix("v")
                for entry in history["versions"]
            ):
                raise CurationError(409, "Archive history already contains the next version")
            for entry in history["versions"]:
                if entry.get("current"):
                    entry["snapshot_key"] = head.object_key
                entry["current"] = False
            reverts = suggestion.id[5:] if suggestion.id.startswith("undo:") else None
            provenance = {
                "operation_id": _operation_id(head.owner, suggestion.id, reverts),
                "reverts_operation_id": reverts,
                "suggestion_id": suggestion.id,
                "scope": suggestion.scope.model_dump(mode="json"),
                "node_id": suggestion.target_node,
                "diff": [r.model_dump() for r in suggestion.diff],
                "resp": ["#corpora-ai", "#" + head.owner],
                "applied_by": head.owner,
                "base_revision": head.revision,
            }
            history["versions"].append(
                {
                    "id": version,
                    "label": version,
                    "title": "AI feature correction",
                    "at": datetime.now(UTC).isoformat(),
                    "current": True,
                    "snapshot_key": head.key_for(revision),
                    "author": {"id": head.owner},
                    "approved_by": None,
                    "notes": [],
                    "files": [{"path": f"corpora/{f}.tf", "kind": "modified"} for f in fields],
                    "ai_change": provenance,
                }
            )
            history_path.write_text(yaml.safe_dump(history, sort_keys=False))
            log_path = root / "ai-changes.json"
            log = json.loads(log_path.read_text()) if log_path.exists() else []
            if not isinstance(log, list):
                raise CurationError(422, "Archive change provenance is invalid")
            log.append({**provenance, "version": version, "revision": revision})
            log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n")
            rebuilt, updated = _load(root)
            after_values = _values(rebuilt, suggestion)
            after_hash = scope_content_hash(rebuilt, scope_nodes(rebuilt, suggestion.scope))
            if (
                after_values != expected
                or after_hash != before.content_hash
                or _untouched_hash(rebuilt, set(fields), suggestion.target_node) != untouched
            ):
                raise CurationError(
                    422,
                    "Rebuilt archive does not preserve the requested feature diff and source text",
                )
            output.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        target.write(path, path.relative_to(root))
            return Plan(
                before=before,
                after=Evidence(
                    revision=revision,
                    digest=digest(output),
                    version=version,
                    content_hash=after_hash,
                    values=after_values,
                ),
            )
    except (
        OSError,
        ValueError,
        TypeError,
        zipfile.BadZipFile,
        yaml.YAMLError,
        StorageError,
    ) as exc:
        raise CurationError(422, "Corpus archive cannot be edited") from exc


class ArchiveDrafts:
    """Concrete draft adapter for already provisioned hosted working corpora."""

    def __init__(self, storage: HostedStorage):
        self.storage = storage

    def authorize(self, owner: str, corpus: str) -> None:
        from common.utils.config import settings

        if settings.hf_read_only or self.storage.resolve(owner, corpus).state != "draft":
            raise CurationError(423, "Corpus is published or locked")

    def confirm(self, owner: str, suggestion: Suggestion, token: str | None) -> None:
        # Fail closed until the panel's bound-confirmation protocol is connected.
        raise CurationError(428, "Corpus-wide edits require the panel confirmation integration")

    def prepare(self, owner: str, suggestion: Suggestion) -> Plan:
        self.authorize(owner, suggestion.scope.corpus)
        head = self.storage.resolve(owner, suggestion.scope.corpus)
        with tempfile.TemporaryDirectory(prefix="ai-stage-") as temporary:
            root = Path(temporary)
            self.storage.download(head, root / "before.corpus")
            plan = edit_archive(root / "before.corpus", root / "after.corpus", head, suggestion)
            self.storage.stage(head, plan.after.revision, root / "after.corpus", plan.after.digest)
            return plan

    def read(self, intent: Intent) -> Evidence:
        head = self.storage.resolve(intent.owner, intent.suggestion.scope.corpus)
        with tempfile.TemporaryDirectory(prefix="ai-current-") as temporary:
            archive = Path(temporary) / "current.corpus"
            self.storage.download(head, archive)
            return inspect_archive(archive, head, intent.suggestion)

    def receipt(self, intent: Intent):
        return self.storage.receipt(intent.owner, intent.id)

    def commit(self, intent: Intent) -> bool:
        self.authorize(intent.owner, intent.suggestion.scope.corpus)
        return self.storage.publish(intent)
