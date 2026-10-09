"""Atomic conversion-event registration, outside the reusable linking core."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from uuid import UUID

from corpora_linking import Detector
from corpora_linking.models import NonEmpty, Value

from .linking_conversion import (
    ConversionInput,
    ConversionReferenceReport,
    detect_converted_references,
)
from .linking_store import SQLiteReferenceStore, VersionConflictError, WorkingRevision


class ConversionEvent(Value):
    authority_id: NonEmpty
    event_id: UUID
    detector_revision: NonEmpty
    input_digest: NonEmpty
    actor_id: NonEmpty
    reason: NonEmpty
    recorded_at: datetime
    report: ConversionReferenceReport


class ConversionEventRegistry:
    """Retry one explicit event without duplicating or overwriting working links.

    An event binds a conversion snapshot, mapping evidence, detector revision and
    ordered semantic outputs. Random allocated reference IDs are excluded from the
    retry digest, never from saved reports. A changed event requires a new identity.
    """

    def __init__(self, store: SQLiteReferenceStore, *, authority_id: str):
        if not authority_id.strip():
            raise ValueError("authority_id is required")
        self.store = store
        self.authority_id = authority_id
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS linking_conversion_events (
                authority_id TEXT NOT NULL, event_id TEXT NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(authority_id, event_id))""")

    def get(self, event_id: UUID) -> ConversionEvent | None:
        with closing(sqlite3.connect(self.store.path)) as db:
            row = db.execute(
                "SELECT record FROM linking_conversion_events WHERE authority_id = ? AND event_id = ?",
                (self.authority_id, str(UUID(str(event_id)))),
            ).fetchone()
        return ConversionEvent.model_validate_json(row[0]) if row else None

    def register(
        self,
        conversion: ConversionInput,
        detector: Detector,
        *,
        event_id: UUID,
        detector_revision: str,
        reason: str,
    ) -> ConversionEvent:
        event_id = UUID(str(event_id))
        report, digest = prepare_conversion(
            conversion, detector, detector_revision=detector_revision, reason=reason
        )
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT record FROM linking_conversion_events WHERE authority_id = ? AND event_id = ?",
                (self.authority_id, str(event_id)),
            ).fetchone()
            if prior:
                event = ConversionEvent.model_validate_json(prior[0])
                if event.input_digest != digest:
                    raise VersionConflictError(
                        "conversion event identity reused with changed input, detector or output"
                    )
                return event
            event = ConversionEvent(
                authority_id=self.authority_id,
                event_id=event_id,
                detector_revision=detector_revision,
                input_digest=digest,
                actor_id=self.store.actor_id,
                reason=reason,
                recorded_at=datetime.now(UTC),
                report=report,
            )
            for item in report.references:
                exists = db.execute(
                    "SELECT 1 FROM linking_revisions WHERE reference_id = ?",
                    (str(item.reference.id),),
                ).fetchone()
                if exists:
                    raise VersionConflictError(
                        "detected reference ID already belongs to working history"
                    )
                revision = WorkingRevision(
                    version=1,
                    actor_id=event.actor_id,
                    reason=reason,
                    recorded_at=event.recorded_at,
                    action="edit",
                    reference=item.reference,
                    conversion=item,
                )
                db.execute(
                    "INSERT INTO linking_revisions(reference_id, version, record) VALUES (?, ?, ?)",
                    (str(item.reference.id), 1, revision.model_dump_json()),
                )
            db.execute(
                "INSERT INTO linking_conversion_events(authority_id, event_id, record) VALUES (?, ?, ?)",
                (self.authority_id, str(event_id), event.model_dump_json()),
            )
            return event


def prepare_conversion(
    conversion: ConversionInput, detector: Detector, *, detector_revision: str, reason: str
) -> tuple[ConversionReferenceReport, str]:
    """Validate detector output and fingerprint semantics identically for all stores."""
    if not detector_revision.strip() or not reason.strip():
        raise ValueError("detector revision and reason are required")
    conversion = ConversionInput.model_validate_json(conversion.model_dump_json())
    report = detect_converted_references(conversion, detector)
    report = ConversionReferenceReport.model_validate_json(report.model_dump_json())
    ids = {item.reference.id for item in report.references}
    if len(ids) != len(report.references):
        raise ValueError("detector emitted duplicate reference IDs")
    for item in report.references:
        ref = item.reference
        if (
            ref.provenance.origin != "automatic"
            or ref.review != "pending"
            or ref.publication != "draft"
            or ref.resolution != "unresolved"
        ):
            raise ValueError("conversion events require automatic unresolved pending drafts")
    semantic = report.model_dump(mode="json")
    for item in semantic["references"]:
        del item["reference"]["id"]
    encoded = json.dumps(
        {"detector_revision": detector_revision, "report": semantic},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return report, digest
