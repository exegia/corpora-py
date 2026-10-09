"""Approved JSON snapshot sidecars and conservative stable-ID reconciliation."""

from collections.abc import Iterable, Mapping
from typing import Literal, Self
from uuid import UUID

from corpora_linking import Reference
from corpora_linking.models import NonEmpty, Value
from pydantic import Field, model_validator

from .linking_store import SQLiteReferenceStore, VersionConflictError


class SnapshotEntry(Value):
    reference: Reference
    working_version: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def approved(self) -> Self:
        if self.reference.review != "approved" or self.reference.publication != "published":
            raise ValueError("snapshot entries require approved published snapshots")
        return self


class PublicationSnapshot(Value):
    schema_version: Literal["corpora-linking-publication/0.1"] = "corpora-linking-publication/0.1"
    authority_id: NonEmpty
    entries: tuple[SnapshotEntry, ...]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({x.reference.id for x in self.entries}) != len(self.entries):
            raise ValueError("duplicate reference IDs in snapshot")
        return self


def _content(reference: Reference) -> dict:
    return reference.model_dump(exclude={"review", "publication", "resolution"})


def _pending(reference: Reference) -> Reference:
    return Reference.model_validate(
        {
            **reference.model_dump(),
            "review": "pending",
            "publication": "draft",
            "resolution": "unresolved",
        }
    )


class ImportDecision(Value):
    authority_id: NonEmpty
    entry: SnapshotEntry
    outcome: Literal["create", "unchanged", "conflict"]
    expected_version: int | None = Field(default=None, ge=1, strict=True)
    diagnostics: tuple[str, ...] = ()


class SnapshotPublicationAdapter:
    """Implements PublicationAdapter without XML, network or working-state mutation."""

    def __init__(self, authority_id: str):
        # Validate at construction, before exporting or importing anything.
        PublicationSnapshot(authority_id=authority_id, entries=())
        self.authority_id = authority_id

    def export(
        self, references: Iterable[Reference], *, versions: Mapping[UUID, int] | None = None
    ) -> bytes:
        entries = []
        for reference in references:
            reference = Reference.model_validate_json(reference.model_dump_json())
            if reference.review != "approved" or reference.publication == "withdrawn":
                raise ValueError("export requires approved, non-withdrawn references")
            published = Reference.model_validate(
                {**reference.model_dump(), "publication": "published"}
            )
            entries.append(
                SnapshotEntry(
                    reference=published,
                    working_version=versions[reference.id] if versions is not None else None,
                )
            )
        snapshot = PublicationSnapshot(
            authority_id=self.authority_id,
            entries=tuple(sorted(entries, key=lambda x: str(x.reference.id))),
        )
        return snapshot.model_dump_json().encode("utf-8")

    def export_working(self, store: SQLiteReferenceStore, reference_ids: Iterable[UUID]) -> bytes:
        references = []
        versions = {}
        for reference_id in reference_ids:
            history = store.history(reference_id)
            if not history:
                raise ValueError("working reference not found")
            latest = history[-1]
            if latest.action != "approve" or latest.validation is None:
                raise ValueError("working snapshot requires audited approval")
            references.append(latest.reference)
            versions[reference_id] = latest.version
        return self.export(references, versions=versions)

    def import_references(self, payload: bytes) -> Iterable[Reference]:
        snapshot = PublicationSnapshot.model_validate_json(payload)
        return tuple(_pending(entry.reference) for entry in snapshot.entries)

    def plan_import(
        self, payload: bytes, store: SQLiteReferenceStore
    ) -> tuple[ImportDecision, ...]:
        snapshot = PublicationSnapshot.model_validate_json(payload)
        decisions = []
        for entry in snapshot.entries:
            outcome: Literal["create", "unchanged", "conflict"]
            history = store.history(entry.reference.id)
            if not history:
                outcome = "create"
                version = None
                diagnostics = ("unknown stable ID; import as pending draft",)
            else:
                latest = history[-1]
                version = latest.version
                outcome = (
                    "unchanged"
                    if _content(latest.reference) == _content(entry.reference)
                    else "conflict"
                )
                diagnostics = (
                    ("identical content; working lifecycle remains authoritative",)
                    if outcome == "unchanged"
                    else ("content differs; explicit reconciliation required",)
                )
            decisions.append(
                ImportDecision(
                    authority_id=snapshot.authority_id,
                    entry=entry,
                    outcome=outcome,
                    expected_version=version,
                    diagnostics=diagnostics,
                )
            )
        return tuple(decisions)

    def apply_import(
        self, decision: ImportDecision, store: SQLiteReferenceStore, *, reason: str
    ) -> int:
        """Apply one explicit decision; conflicts never overwrite or auto-approve.

        Upstream versions are evidence within authority_id, not local CAS versions.
        A batch is intentionally a sequence of per-reference operations.
        """
        decision = ImportDecision.model_validate_json(decision.model_dump_json())
        if not reason.strip():
            raise ValueError("import reason is required")
        if decision.outcome == "conflict":
            raise ValueError("conflicting snapshots require explicit reconciliation")
        if decision.outcome == "unchanged":
            history = store.history(decision.entry.reference.id)
            if (
                not history
                or history[-1].version != decision.expected_version
                or _content(history[-1].reference) != _content(decision.entry.reference)
            ):
                raise VersionConflictError("working reference changed after import planning")
            return history[-1].version
        if decision.expected_version is not None:
            raise ValueError("new imports must expect no existing local version")
        incoming = _pending(decision.entry.reference)
        upstream = decision.entry.working_version
        return store.save(
            incoming,
            expected_version=None,
            reason=f"{reason}; imported authority={decision.authority_id}; upstream_version={upstream}",
        )


def render_cusx_jump(entry: SnapshotEntry) -> bytes:
    """Render one existing USX jmp wrapper, for explicit source-range placement.

    Only resolved document/structural destinations are renderable. Caller verifies
    inventory/anchor advertisement and insertion at the pinned source range.
    Complete lossless metadata remains in the snapshot sidecar with the same ID.
    """
    from urllib.parse import quote
    from xml.etree import ElementTree

    from corpora_linking import StructuralLocator, TextLocator

    entry = SnapshotEntry.model_validate_json(entry.model_dump_json())
    reference = entry.reference
    if reference.resolution != "resolved":
        raise ValueError("unresolved references have no exact C-USX destination")
    if len(reference.source.locators) != 1 or not isinstance(
        reference.source.locators[0], TextLocator
    ):
        raise ValueError("jmp rendering requires one pinned source text selection")
    target = reference.target
    segments = (target.package_id, target.revision, target.document_id)
    if any(segment is None or segment in ("", ".", "..") for segment in segments):
        raise ValueError("destination requires a concrete package/revision/document")
    href = "x-corpora:/" + "/".join(quote(segment or "", safe="") for segment in segments)
    if target.locators:
        if len(target.locators) != 1 or not isinstance(target.locators[0], StructuralLocator):
            raise ValueError(
                "text/native/citation destinations require an explicit published anchor binding"
            )
        href += "#" + quote(target.locators[0].anchor_id, safe="")
    element = ElementTree.Element(
        "char", {"style": "jmp", "link-href": href, "link-id": f"urn:uuid:{reference.id}"}
    )
    source_text = reference.source.locators[0].exact
    if any(
        not (
            ord(char) in (9, 10, 13)
            or 0x20 <= ord(char) <= 0xD7FF
            or 0xE000 <= ord(char) <= 0xFFFD
            or 0x10000 <= ord(char) <= 0x10FFFF
        )
        for char in source_text
    ):
        raise ValueError("source quote contains characters unsupported by XML 1.0")
    element.text = source_text
    return ElementTree.tostring(element, encoding="utf-8")
