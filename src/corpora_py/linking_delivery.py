"""Trusted delivery-provider receipts, separate from editorial publication state.

No network calls. Server integration records provider evidence after distribution
or removal; a user acknowledgment alone never becomes a delivery confirmation.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import psycopg
from corpora_linking.models import NonEmpty, Value
from psycopg.types.json import Jsonb

from .linking_ledger import PublicationEvent
from .linking_postgres import PostgreSQLReferenceStore
from .linking_postgres_events import _authority, _lock_event


class DeliveryEvidence(Value):
    receipt_id: UUID
    publication_event_id: UUID
    destination_id: NonEmpty
    provider_id: NonEmpty
    provider_receipt: NonEmpty
    artifact_digest: NonEmpty
    status: Literal["delivered", "removed", "failed"]


class DeliveryReceipt(Value):
    evidence: DeliveryEvidence
    publication: PublicationEvent
    actor_id: NonEmpty
    recorded_at: datetime


class PostgreSQLDeliveryReceipts:
    """Admin-only trusted provider bridge; append-only, per-destination evidence."""

    def __init__(self, store: PostgreSQLReferenceStore, *, provider_id: str):
        if not provider_id.strip():
            raise ValueError("provider identity required")
        self.store, self.provider_id = store, provider_id

    def record(self, evidence: DeliveryEvidence) -> DeliveryReceipt:
        evidence = DeliveryEvidence.model_validate(evidence.model_dump())
        if evidence.provider_id != self.provider_id:
            raise ValueError("receipt provider differs from configured authority")
        with psycopg.connect(self.store.dsn) as db:
            actor = self.store._authorize(db, "admin")
            authority = _authority(db, self.store)
            _lock_event(db, self.store, "delivery", evidence.receipt_id)
            row = db.execute(
                "SELECT record FROM reference_working.publication_events WHERE space_id = %s AND authority_id = %s AND event_id = %s",
                (self.store.space_id, authority, evidence.publication_event_id),
            ).fetchone()
            if not row:
                raise ValueError("publication event unavailable")
            publication = PublicationEvent.model_validate(row[0])
            self.store._check_history_access(db, actor, publication.reference_id)
            if evidence.artifact_digest != publication.artifact_digest:
                raise ValueError("receipt artifact differs from publication event")
            if (evidence.status == "delivered" and publication.action != "publish") or (
                evidence.status == "removed" and publication.action != "withdraw"
            ):
                raise ValueError("receipt status contradicts publication action")
            prior = db.execute(
                "SELECT record FROM reference_working.delivery_receipts WHERE space_id = %s AND receipt_id = %s",
                (self.store.space_id, evidence.receipt_id),
            ).fetchone()
            if prior:
                receipt = DeliveryReceipt.model_validate(prior[0])
                if receipt.evidence != evidence or receipt.actor_id != str(actor):
                    raise ValueError("receipt ID already belongs to different evidence")
                return receipt
            receipt = DeliveryReceipt(
                evidence=evidence,
                publication=publication,
                actor_id=str(actor),
                recorded_at=datetime.now(UTC),
            )
            db.execute(
                "INSERT INTO reference_working.delivery_receipts (space_id, authority_id, receipt_id, publication_event_id, record) VALUES (%s, %s, %s, %s, %s)",
                (
                    self.store.space_id,
                    authority,
                    evidence.receipt_id,
                    evidence.publication_event_id,
                    Jsonb(receipt.model_dump(mode="json")),
                ),
            )
            return receipt

    def history(self, reference_id: UUID) -> tuple[DeliveryReceipt, ...]:
        with psycopg.connect(self.store.dsn) as db:
            actor = self.store._authorize(db, None)
            self.store._check_history_access(db, actor, reference_id)
            rows = db.execute(
                "SELECT d.record FROM reference_working.delivery_receipts d JOIN reference_working.publication_events p ON p.space_id = d.space_id AND p.authority_id = d.authority_id AND p.event_id = d.publication_event_id WHERE d.space_id = %s AND p.reference_id = %s ORDER BY d.record->>'recorded_at', d.receipt_id",
                (self.store.space_id, reference_id),
            ).fetchall()
            return tuple(DeliveryReceipt.model_validate(row[0]) for row in rows)
