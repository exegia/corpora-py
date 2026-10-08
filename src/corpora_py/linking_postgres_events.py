"""Authenticated PostgreSQL conversion registration and publication ledger."""

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import psycopg
from corpora_linking import Detector, Reference
from psycopg.types.json import Jsonb

from .linking_conversion import ConversionInput
from .linking_events import ConversionEvent, prepare_conversion
from .linking_ledger import PublicationEvent, PublicationLedger
from .linking_postgres import PostgreSQLReferenceStore
from .linking_publication import SnapshotEntry, SnapshotPublicationAdapter
from .linking_store import VersionConflictError, WorkingRevision


def _authority(db: psycopg.Connection, store: PostgreSQLReferenceStore) -> str:
    row = db.execute(
        "SELECT authority_id FROM reference_working.spaces WHERE id = %s FOR SHARE",
        (store.space_id,),
    ).fetchone()
    if row is None:
        raise PermissionError("reference space unavailable")
    return row[0]


def _lock_event(
    db: psycopg.Connection, store: PostgreSQLReferenceStore, kind: str, event_id: UUID
) -> None:
    # Separate namespaces; hash collisions only serialize otherwise independent events.
    key = int.from_bytes(
        hashlib.sha256(f"{store.space_id}/{kind}/{event_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    db.execute("SELECT pg_advisory_xact_lock(%s)", (key,))


def _current(
    db: psycopg.Connection, store: PostgreSQLReferenceStore, reference_id: UUID
) -> WorkingRevision | None:
    head = db.execute(
        "SELECT current_version FROM reference_working.heads WHERE space_id = %s AND reference_id = %s FOR UPDATE",
        (store.space_id, reference_id),
    ).fetchone()
    if head is None:
        return None
    row = db.execute(
        "SELECT version, actor_id, recorded_at, reason, action, reference, validation, conversion FROM reference_working.revisions WHERE space_id = %s AND reference_id = %s AND version = %s",
        (store.space_id, reference_id, head[0]),
    ).fetchone()
    if row is None:
        raise ValueError("working head has no revision")
    return store._decode(row)


class PostgreSQLConversionEventRegistry:
    store: PostgreSQLReferenceStore

    def __init__(self, store: PostgreSQLReferenceStore):
        self.store = store

    def get(self, event_id: UUID) -> ConversionEvent | None:
        with psycopg.connect(self.store.dsn) as db:
            self.store._authorize(db, None)
            row = db.execute(
                "SELECT record FROM reference_working.conversion_events WHERE space_id = %s AND authority_id = %s AND event_id = %s",
                (self.store.space_id, _authority(db, self.store), event_id),
            ).fetchone()
            return ConversionEvent.model_validate(row[0]) if row else None

    def register(
        self,
        conversion: ConversionInput,
        detector: Detector,
        *,
        event_id: UUID,
        detector_revision: str,
        reason: str,
    ) -> ConversionEvent:
        report, digest = prepare_conversion(
            conversion, detector, detector_revision=detector_revision, reason=reason
        )
        try:
            with psycopg.connect(self.store.dsn) as db:
                actor = self.store._authorize(db, "contribute")
                authority = _authority(db, self.store)
                _lock_event(db, self.store, "conversion", event_id)
                row = db.execute(
                    "SELECT record FROM reference_working.conversion_events WHERE space_id = %s AND authority_id = %s AND event_id = %s",
                    (self.store.space_id, authority, event_id),
                ).fetchone()
                if row:
                    prior = ConversionEvent.model_validate(row[0])
                    if prior.input_digest != digest:
                        raise VersionConflictError(
                            "conversion event identity reused with changed input, detector or output"
                        )
                    return prior
                event = ConversionEvent(
                    authority_id=authority,
                    event_id=event_id,
                    detector_revision=detector_revision,
                    input_digest=digest,
                    actor_id=str(actor),
                    reason=reason,
                    recorded_at=datetime.now(UTC),
                    report=report,
                )
                for item in sorted(report.references, key=lambda item: str(item.reference.id)):
                    db.execute(
                        "INSERT INTO reference_working.heads VALUES (%s, %s, 1)",
                        (self.store.space_id, item.reference.id),
                    )
                    self.store._insert_revision(
                        db,
                        WorkingRevision(
                            version=1,
                            actor_id=str(actor),
                            reason=reason,
                            recorded_at=event.recorded_at,
                            action="edit",
                            reference=item.reference,
                            conversion=item,
                        ),
                    )
                db.execute(
                    "INSERT INTO reference_working.conversion_events (space_id, authority_id, event_id, fingerprint, detector_revision, report, actor_id, recorded_at, record) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        self.store.space_id,
                        authority,
                        event_id,
                        digest.removeprefix("sha256:"),
                        detector_revision,
                        Jsonb(report.model_dump(mode="json")),
                        actor,
                        event.recorded_at,
                        Jsonb(event.model_dump(mode="json")),
                    ),
                )
                return event
        except psycopg.errors.UniqueViolation as exc:
            raise VersionConflictError(
                "detected reference ID already belongs to working history"
            ) from exc


class PostgreSQLPublicationLedger(PublicationLedger):
    """Atomic ledger events; no artifact distribution or remote delivery claims."""

    store: PostgreSQLReferenceStore

    def __init__(self, store: PostgreSQLReferenceStore):
        self.store = store
        with psycopg.connect(store.dsn) as db:
            store._authorize(db, None)
            self.authority_id = _authority(db, store)

    def history(self, reference_id: UUID) -> tuple[PublicationEvent, ...]:
        with psycopg.connect(self.store.dsn) as db:
            self.store._authorize(db, None)
            rows = db.execute(
                "SELECT record FROM reference_working.publication_events WHERE space_id = %s AND reference_id = %s ORDER BY resulting_version",
                (self.store.space_id, reference_id),
            ).fetchall()
            return tuple(PublicationEvent.model_validate(row[0]) for row in rows)

    def pending_removals(self) -> tuple[PublicationEvent, ...]:
        with psycopg.connect(self.store.dsn) as db:
            self.store._authorize(db, None)
            rows = db.execute(
                "SELECT record FROM reference_working.publication_events WHERE space_id = %s AND action = 'withdraw' ORDER BY resulting_version, event_id",
                (self.store.space_id,),
            ).fetchall()
            return tuple(PublicationEvent.model_validate(row[0]) for row in rows)

    def export_current(self, reference_ids: Iterable[UUID]) -> bytes:
        with psycopg.connect(self.store.dsn) as db:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            self.store._authorize(db, None)
            authority = _authority(db, self.store)
            references, versions = [], {}
            for reference_id in reference_ids:
                row = db.execute(
                    "SELECT r.version, r.actor_id, r.recorded_at, r.reason, r.action, r.reference, r.validation, r.conversion FROM reference_working.heads h JOIN reference_working.revisions r ON (r.space_id, r.reference_id, r.version) = (h.space_id, h.reference_id, h.current_version) WHERE h.space_id = %s AND h.reference_id = %s",
                    (self.store.space_id, reference_id),
                ).fetchone()
                if row is None:
                    raise ValueError("working reference not found")
                latest = self.store._decode(row)
                if latest.reference.publication == "withdrawn":
                    continue
                if latest.action not in ("approve", "publish") or latest.validation is None:
                    raise ValueError("next snapshot requires audited approved references")
                references.append(latest.reference)
                versions[reference_id] = latest.version
            return SnapshotPublicationAdapter(authority).export(references, versions=versions)

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
        with psycopg.connect(self.store.dsn) as db:
            actor = self.store._authorize(db, "publish")
            authority = _authority(db, self.store)
            if authority != self.authority_id:
                raise ValueError("ledger authority changed")
            _lock_event(db, self.store, "publication", event_id)
            row = db.execute(
                "SELECT record FROM reference_working.publication_events WHERE space_id = %s AND authority_id = %s AND event_id = %s",
                (self.store.space_id, authority, event_id),
            ).fetchone()
            if row:
                event = PublicationEvent.model_validate(row[0])
                if (
                    event.reference_id != reference_id
                    or event.action != action
                    or event.expected_version != expected_version
                    or event.reason != reason
                    or event.actor_id != str(actor)
                    or (digest is not None and event.artifact_digest != digest)
                ):
                    raise ValueError("event ID already belongs to another acknowledgment")
                return event
            current = _current(db, self.store, reference_id)
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
                row = db.execute(
                    "SELECT record FROM reference_working.publication_events WHERE space_id = %s AND reference_id = %s ORDER BY resulting_version DESC LIMIT 1",
                    (self.store.space_id, reference_id),
                ).fetchone()
                prior = PublicationEvent.model_validate(row[0]) if row else None
                if prior is None or prior.action != "publish" or prior.authority_id != authority:
                    raise ValueError("published reference has no matching ledger acknowledgment")
                snapshot_version, digest = prior.snapshot_version, prior.artifact_digest
                published = Reference.model_validate(
                    {**current.reference.model_dump(), "publication": "withdrawn"}
                )
            event = PublicationEvent(
                event_id=event_id,
                reference_id=reference_id,
                authority_id=authority,
                artifact_digest=digest or "",
                snapshot_version=snapshot_version,
                expected_version=expected_version,
                working_version=current.version + 1,
                action=action,
                actor_id=str(actor),
                reason=reason,
                recorded_at=datetime.now(UTC),
            )
            revision = WorkingRevision(
                version=event.working_version,
                actor_id=str(actor),
                reason=reason,
                recorded_at=event.recorded_at,
                action=action,
                reference=published,
                validation=current.validation,
                conversion=current.conversion,
            )
            self.store._insert_revision(db, revision)
            db.execute(
                "UPDATE reference_working.heads SET current_version = %s WHERE space_id = %s AND reference_id = %s",
                (revision.version, self.store.space_id, reference_id),
            )
            db.execute(
                "INSERT INTO reference_working.publication_events (space_id, authority_id, event_id, reference_id, approval_version, resulting_version, action, snapshot_sha256, actor_id, recorded_at, reason, record) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    self.store.space_id,
                    authority,
                    event_id,
                    reference_id,
                    snapshot_version,
                    revision.version,
                    "acknowledge" if action == "publish" else "withdraw",
                    event.artifact_digest.removeprefix("sha256:"),
                    actor,
                    event.recorded_at,
                    reason,
                    Jsonb(event.model_dump(mode="json")),
                ),
            )
            return event
