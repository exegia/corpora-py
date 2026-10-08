"""Offline SQLite working-reference history; no Supabase or publication I/O."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from corpora_linking import CitationLocator, Reference, ResolutionResult, Resolver
from corpora_linking.models import NonEmpty, Value
from pydantic import Field

from .linking_conversion import ConvertedReference


class VersionConflictError(ValueError):
    """The caller's working revision is no longer current."""


class ValidationReport(Value):
    source: ResolutionResult
    target: ResolutionResult


class WorkingRevision(Value):
    version: int = Field(ge=1, strict=True)
    actor_id: NonEmpty
    reason: NonEmpty
    recorded_at: datetime
    action: Literal["edit", "resolve", "approve", "reject", "publish", "withdraw", "reopen"]
    reference: Reference
    validation: ValidationReport | None = None
    conversion: ConvertedReference | None = None


class SQLiteReferenceStore:
    """Append-only working revisions with compare-and-swap and audited review.

    Use a local file path; caller identity is supplied by the trusted integration.
    This offline adapter implements no authentication or RLS. Publication
    acknowledgments use the separate local ledger. Approval is a reviewed working snapshot, not a deployment/export.
    """

    def __init__(self, path: str | Path, *, actor_id: str):
        if not actor_id or not actor_id.strip():
            raise ValueError("actor_id is required")
        if str(path) == ":memory:":
            raise ValueError("working history requires a local file")
        self.path = str(path)
        self.actor_id = actor_id
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS linking_revisions (
                reference_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version > 0),
                record TEXT NOT NULL, PRIMARY KEY(reference_id, version))""")

    def history(self, reference_id: UUID) -> tuple[WorkingRevision, ...]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT record FROM linking_revisions WHERE reference_id = ? ORDER BY version",
                (str(reference_id),),
            ).fetchall()
        return tuple(WorkingRevision.model_validate_json(row[0]) for row in rows)

    def get(self, reference_id: UUID) -> Reference | None:
        revisions = self.history(reference_id)
        return revisions[-1].reference if revisions else None

    def save(
        self,
        reference: Reference,
        *,
        expected_version: int | None,
        reason: str = "working edit",
        conversion: ConvertedReference | None = None,
    ) -> int:
        """Create/update pending drafts only; edits invalidate prior approval."""
        reference = Reference.model_validate(reference.model_dump())
        if reference.review != "pending" or reference.publication != "draft":
            raise ValueError("save accepts only pending draft references")
        return self._write(
            reference,
            expected_version=expected_version,
            reason=reason,
            action="edit",
            conversion=conversion,
        )

    def _current(self, reference_id: UUID, expected_version: int) -> Reference:
        revisions = self.history(reference_id)
        if not revisions or revisions[-1].version != expected_version:
            raise VersionConflictError("working reference version changed")
        return revisions[-1].reference

    @staticmethod
    def _validate(reference: Reference, resolver: Resolver) -> ValidationReport:
        return ValidationReport(
            source=resolver.resolve(reference.source), target=resolver.resolve(reference.target)
        )

    def resolve_target(
        self, reference_id: UUID, *, expected_version: int, resolver: Resolver, reason: str
    ) -> int:
        current = self._current(reference_id, expected_version)
        report = self._validate(current, resolver)
        result = report.target
        target = result.candidates[0] if result.status == "resolved" else current.target
        updated = Reference.model_validate(
            {
                **current.model_dump(),
                "target": target,
                "resolution": result.status,
                "review": "pending",
            }
        )
        return self._write(
            updated,
            expected_version=expected_version,
            reason=reason,
            action="resolve",
            validation=report,
        )

    def approve(
        self,
        reference_id: UUID,
        *,
        expected_version: int,
        resolver: Resolver,
        reason: str,
        allow_unresolved_target: bool = False,
    ) -> int:
        current = self._current(reference_id, expected_version)
        report = self._validate(current, resolver)
        if report.source.status != "resolved" or report.source.candidates != (current.source,):
            raise ValueError("approval requires a verified current source")
        target_verified = report.target.status == "resolved" and report.target.candidates == (
            current.target,
        )
        if not target_verified:
            unresolved_citation = report.target.status in ("unresolved", "unavailable") and all(
                isinstance(x, CitationLocator) for x in current.target.locators
            )
            if not allow_unresolved_target or not unresolved_citation:
                raise ValueError(
                    "target must be verified or explicitly accepted as an unresolved citation/work"
                )
        updated = Reference.model_validate(
            {**current.model_dump(), "review": "approved", "resolution": report.target.status}
        )
        return self._write(
            updated,
            expected_version=expected_version,
            reason=reason,
            action="approve",
            validation=report,
        )

    def reject(self, reference_id: UUID, *, expected_version: int, reason: str) -> int:
        current = self._current(reference_id, expected_version)
        updated = Reference.model_validate({**current.model_dump(), "review": "rejected"})
        return self._write(
            updated, expected_version=expected_version, reason=reason, action="reject"
        )

    def reopen(self, reference_id: UUID, *, expected_version: int, reason: str) -> int:
        current = self._current(reference_id, expected_version)
        if current.publication != "withdrawn":
            raise ValueError("reopening requires a withdrawn reference")
        updated = Reference.model_validate(
            {**current.model_dump(), "review": "pending", "publication": "draft"}
        )
        return self._write(
            updated, expected_version=expected_version, reason=reason, action="reopen"
        )

    def _write(
        self,
        reference: Reference,
        *,
        expected_version: int | None,
        reason: str,
        action: Literal["edit", "resolve", "approve", "reject", "publish", "withdraw", "reopen"],
        validation: ValidationReport | None = None,
        conversion: ConvertedReference | None = None,
    ) -> int:
        if expected_version is not None and (
            type(expected_version) is not int or expected_version < 1
        ):
            raise ValueError("expected_version must be a positive integer or None for creation")
        if not reason.strip():
            raise ValueError("revision reason is required")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT version, record FROM linking_revisions WHERE reference_id = ? ORDER BY version DESC LIMIT 1",
                (str(reference.id),),
            ).fetchone()
            actual = row[0] if row else None
            if actual != expected_version:
                raise VersionConflictError("working reference version changed")
            previous_revision = WorkingRevision.model_validate_json(row[1]) if row else None
            revision = prepare_revision(
                reference,
                previous_revision=previous_revision,
                actor_id=self.actor_id,
                reason=reason,
                action=action,
                validation=validation,
                conversion=conversion,
            )
            if previous_revision is not None and revision.version == previous_revision.version:
                return revision.version
            db.execute(
                "INSERT INTO linking_revisions(reference_id, version, record) VALUES (?, ?, ?)",
                (str(reference.id), revision.version, revision.model_dump_json()),
            )
            return revision.version


def prepare_revision(
    reference: Reference,
    *,
    previous_revision: WorkingRevision | None,
    actor_id: str,
    reason: str,
    action: Literal["edit", "resolve", "approve", "reject", "publish", "withdraw", "reopen"],
    validation: ValidationReport | None = None,
    conversion: ConvertedReference | None = None,
) -> WorkingRevision:
    """Shared lifecycle enforcement after the storage adapter checks CAS."""
    reference = Reference.model_validate(reference.model_dump())
    if not reason.strip():
        raise ValueError("revision reason is required")
    if previous_revision is not None:
        previous = previous_revision.reference
        if conversion is None and previous.source == reference.source:
            conversion = previous_revision.conversion
        if previous.publication != "draft" and not (
            action == "reopen" and previous.publication == "withdrawn"
        ):
            raise ValueError("published snapshot requires a publication reconciliation adapter")
        if action in ("approve", "reject") and previous.review != "pending":
            raise ValueError("review transitions require a pending draft")
        if (
            action == "edit"
            and previous == reference
            and previous_revision.conversion == conversion
        ):
            return previous_revision
    elif action != "edit":
        raise ValueError("reference must be created before lifecycle transitions")
    if conversion is not None and (
        conversion.reference.id != reference.id or conversion.reference.source != reference.source
    ):
        raise ValueError("conversion evidence belongs to another reference or source")
    revision = WorkingRevision(
        version=(previous_revision.version if previous_revision else 0) + 1,
        actor_id=actor_id,
        reason=reason,
        recorded_at=datetime.now(UTC),
        action=action,
        reference=reference,
        validation=validation,
        conversion=conversion,
    )
    return revision
