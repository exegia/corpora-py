"""Offline acknowledgment ledger; records events but never distributes artifacts."""

import hashlib
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from corpora_linking import Reference
from corpora_linking.models import NonEmpty, Value
from pydantic import Field

from .linking_publication import PublicationSnapshot, SnapshotEntry
from .linking_store import SQLiteReferenceStore, VersionConflictError, WorkingRevision


class PublicationEvent(Value):
    event_id: UUID
    reference_id: UUID
    authority_id: NonEmpty
    artifact_digest: NonEmpty
    snapshot_version: int = Field(ge=1, strict=True)
    expected_version: int = Field(ge=1, strict=True)
    working_version: int = Field(ge=1, strict=True)
    action: Literal["publish", "withdraw"]
    actor_id: NonEmpty
    reason: NonEmpty
    recorded_at: datetime


class PublicationLedger:
    """Atomic working-state acknowledgment and append-only publication events.

    The trusted caller supplies the local authority and event identity. Acknowledgment
    records a claimed distribution/removal decision, not evidence of network delivery.
    """

    def __init__(self, store: SQLiteReferenceStore, *, authority_id: str):
        PublicationSnapshot(authority_id=authority_id, entries=())
        self.store = store
        self.authority_id = authority_id
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS linking_publication_events (
                event_id TEXT PRIMARY KEY, reference_id TEXT NOT NULL,
                working_version INTEGER NOT NULL, record TEXT NOT NULL)""")

    def history(self, reference_id: UUID) -> tuple[PublicationEvent, ...]:
        with closing(sqlite3.connect(self.store.path)) as db:
            rows = db.execute(
                "SELECT record FROM linking_publication_events WHERE reference_id = ? ORDER BY working_version",
                (str(reference_id),),
            ).fetchall()
        return tuple(PublicationEvent.model_validate_json(row[0]) for row in rows)

    def acknowledge_snapshot(
        self,
        payload: bytes,
        reference_id: UUID,
        *,
        event_id: UUID,
        expected_version: int,
        reason: str,
    ) -> PublicationEvent:
        snapshot = PublicationSnapshot.model_validate_json(payload)
        if snapshot.authority_id != self.authority_id:
            raise ValueError("snapshot authority differs from local ledger")
        entries = [entry for entry in snapshot.entries if entry.reference.id == reference_id]
        if not entries or entries[0].working_version is None:
            raise ValueError("acknowledgment requires a versioned snapshot entry")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        return self._record(
            reference_id,
            event_id=event_id,
            expected_version=expected_version,
            reason=reason,
            action="publish",
            digest=digest,
            entry=entries[0],
        )

    def withdraw(
        self, reference_id: UUID, *, event_id: UUID, expected_version: int, reason: str
    ) -> PublicationEvent:
        return self._record(
            reference_id,
            event_id=event_id,
            expected_version=expected_version,
            reason=reason,
            action="withdraw",
        )

    def pending_removals(self) -> tuple[PublicationEvent, ...]:
        """All recorded withdrawal tombstones, including superseded artifacts.

        They are not delivery confirmations; distribution adapters must track removal.
        """
        with closing(sqlite3.connect(self.store.path)) as db:
            rows = db.execute(
                "SELECT record FROM linking_publication_events ORDER BY working_version, event_id"
            ).fetchall()
        return tuple(
            event
            for row in rows
            if (event := PublicationEvent.model_validate_json(row[0])).action == "withdraw"
        )

    def export_current(self, reference_ids: Iterable[UUID]) -> bytes:
        """Prepare the next snapshot, omitting withdrawn records without deletion."""
        from .linking_publication import SnapshotPublicationAdapter

        references = []
        versions = {}
        for reference_id in reference_ids:
            history = self.store.history(reference_id)
            if not history:
                raise ValueError("working reference not found")
            latest = history[-1]
            if latest.reference.publication == "withdrawn":
                continue
            if latest.action not in ("approve", "publish") or latest.validation is None:
                raise ValueError("next snapshot requires audited approved references")
            references.append(latest.reference)
            versions[reference_id] = latest.version
        return SnapshotPublicationAdapter(self.authority_id).export(references, versions=versions)

    def _record(
        self,
        reference_id: UUID,
        *,
        event_id: UUID,
        expected_version: int,
        reason: str,
        action: Literal["publish", "withdraw"],
        digest: str | None = None,
        entry: SnapshotEntry | None = None,
    ) -> PublicationEvent:
        if type(expected_version) is not int or expected_version < 1 or not reason.strip():
            raise ValueError("a positive expected version and nonempty reason are required")
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT record FROM linking_publication_events WHERE event_id = ?", (str(event_id),)
            ).fetchone()
            if replay:
                event = PublicationEvent.model_validate_json(replay[0])
                if (
                    event.reference_id != reference_id
                    or event.action != action
                    or event.expected_version != expected_version
                    or event.reason != reason
                    or event.actor_id != self.store.actor_id
                    or event.authority_id != self.authority_id
                    or (digest is not None and event.artifact_digest != digest)
                ):
                    raise ValueError("event ID already belongs to another acknowledgment")
                return event
            row = db.execute(
                "SELECT record FROM linking_revisions WHERE reference_id = ? ORDER BY version DESC LIMIT 1",
                (str(reference_id),),
            ).fetchone()
            current = WorkingRevision.model_validate_json(row[0]) if row else None
            if current is None or current.version != expected_version:
                raise VersionConflictError("working reference changed before acknowledgment")
            if action == "publish":
                if (
                    entry is None
                    or entry.working_version != current.version
                    or current.action != "approve"
                    or current.validation is None
                    or current.reference.publication != "draft"
                ):
                    raise ValueError("snapshot must match the current audited approval")
                published = Reference.model_validate(
                    {**current.reference.model_dump(), "publication": "published"}
                )
                if published != entry.reference:
                    raise ValueError("snapshot content differs from approved working reference")
                snapshot_version = current.version
            else:
                if current.reference.publication != "published":
                    raise ValueError("withdrawal requires an acknowledged published reference")
                prior_row = db.execute(
                    "SELECT record FROM linking_publication_events WHERE reference_id = ? ORDER BY working_version DESC LIMIT 1",
                    (str(reference_id),),
                ).fetchone()
                prior = PublicationEvent.model_validate_json(prior_row[0]) if prior_row else None
                if (
                    prior is None
                    or prior.action != "publish"
                    or prior.authority_id != self.authority_id
                ):
                    raise ValueError("published reference has no matching ledger acknowledgment")
                snapshot_version = prior.snapshot_version
                digest = prior.artifact_digest
                published = Reference.model_validate(
                    {**current.reference.model_dump(), "publication": "withdrawn"}
                )
            event = PublicationEvent(
                event_id=event_id,
                reference_id=reference_id,
                authority_id=self.authority_id,
                artifact_digest=digest or "",
                snapshot_version=snapshot_version,
                expected_version=expected_version,
                working_version=current.version + 1,
                action=action,
                actor_id=self.store.actor_id,
                reason=reason,
                recorded_at=datetime.now(UTC),
            )
            revision = WorkingRevision(
                version=event.working_version,
                actor_id=event.actor_id,
                reason=reason,
                recorded_at=event.recorded_at,
                action=action,
                reference=published,
                validation=current.validation,
                conversion=current.conversion,
            )
            db.execute(
                "INSERT INTO linking_revisions(reference_id, version, record) VALUES (?, ?, ?)",
                (str(reference_id), revision.version, revision.model_dump_json()),
            )
            db.execute(
                "INSERT INTO linking_publication_events(event_id, reference_id, working_version, record) VALUES (?, ?, ?, ?)",
                (str(event_id), str(reference_id), event.working_version, event.model_dump_json()),
            )
            return event
