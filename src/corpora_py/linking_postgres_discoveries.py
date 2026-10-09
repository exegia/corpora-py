"""Authenticated PostgreSQL scholarly discovery history; no schema deployment."""

from typing import Literal
from uuid import UUID

import psycopg
from corpora_linking import CitationDiscovery, ConversionMapping, TextSnapshot
from psycopg.types.json import Jsonb

from .linking_discoveries import (
    DiscoveryRevision,
    SQLiteDiscoveryStore,
    prepare_discovery_decision,
    prepare_discovery_registration,
)
from .linking_postgres import PostgreSQLReferenceStore
from .linking_postgres_events import _authority, _lock_event
from .linking_store import VersionConflictError


class PostgreSQLDiscoveryStore(SQLiteDiscoveryStore):
    """Same discovery decisions as SQLite, with fresh authorization per operation.

    Advisory locks serialize registration and CAS for a discovery; history rows
    are append-only by server grants. No current pointer duplicates history state.
    """

    store: PostgreSQLReferenceStore

    def __init__(self, store: PostgreSQLReferenceStore):
        self.store = store

    def history(self, discovery_id: UUID) -> tuple[DiscoveryRevision, ...]:
        with psycopg.connect(self.store.dsn) as db:
            actor = self.store._authorize(db, None)
            rows = db.execute(
                "SELECT record FROM reference_working.discovery_revisions WHERE space_id = %s AND discovery_id = %s ORDER BY version",
                (self.store.space_id, discovery_id),
            ).fetchall()
            history = tuple(DiscoveryRevision.model_validate(row[0]) for row in rows)
            self.store._check_access(db, actor, history)
            return history

    def _append(self, db: psycopg.Connection, revision: DiscoveryRevision) -> None:
        db.execute(
            "INSERT INTO reference_working.discovery_revisions VALUES (%s, %s, %s, %s)",
            (
                self.store.space_id,
                revision.discovery.id,
                revision.version,
                Jsonb(revision.model_dump(mode="json")),
            ),
        )

    def register(
        self,
        discovery: CitationDiscovery,
        snapshot: TextSnapshot,
        *,
        event_id: UUID,
        reason: str,
        mappings: tuple[ConversionMapping, ...] = (),
    ) -> DiscoveryRevision:
        discovery, mappings, digest = prepare_discovery_registration(
            discovery, snapshot, reason=reason, mappings=mappings
        )
        try:
            with psycopg.connect(self.store.dsn) as db:
                actor = self.store._authorize(db, "contribute")
                self.store._check_access(db, actor, (discovery, mappings))
                authority = _authority(db, self.store)
                _lock_event(db, self.store, "discovery-registration", event_id)
                row = db.execute(
                    "SELECT digest, record FROM reference_working.discovery_events WHERE space_id = %s AND authority_id = %s AND event_id = %s",
                    (self.store.space_id, authority, event_id),
                ).fetchone()
                if row:
                    original = DiscoveryRevision.model_validate(row[1])
                    self.store._check_access(db, actor, original)
                    if row[0] != digest:
                        raise VersionConflictError("discovery event reused with changed evidence")
                    return original
                _lock_event(db, self.store, "discovery", discovery.id)
                exists = db.execute(
                    "SELECT 1 FROM reference_working.discovery_revisions WHERE space_id = %s AND discovery_id = %s",
                    (self.store.space_id, discovery.id),
                ).fetchone()
                if exists:
                    raise VersionConflictError("discovery ID already belongs to history")
                from datetime import UTC, datetime

                revision = DiscoveryRevision(
                    version=1,
                    action="register",
                    actor_id=str(actor),
                    reason=reason,
                    recorded_at=datetime.now(UTC),
                    discovery=discovery,
                    mappings=mappings,
                )
                self._append(db, revision)
                db.execute(
                    "INSERT INTO reference_working.discovery_events (space_id, authority_id, event_id, discovery_id, digest, record) VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        self.store.space_id,
                        authority,
                        event_id,
                        discovery.id,
                        digest,
                        Jsonb(revision.model_dump(mode="json")),
                    ),
                )
                return revision
        except psycopg.errors.UniqueViolation as exc:
            raise VersionConflictError("discovery registration conflicted") from exc

    def _transition(
        self,
        discovery_id: UUID,
        *,
        expected_version: int,
        reason: str,
        action: Literal["identify", "select", "reject"],
        replacement: CitationDiscovery | None = None,
        work_id: str | None = None,
    ) -> DiscoveryRevision:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected version must be a positive integer")
        try:
            with psycopg.connect(self.store.dsn) as db:
                actor = self.store._authorize(
                    db, "review" if action in ("select", "reject") else "contribute"
                )
                _lock_event(db, self.store, "discovery", discovery_id)
                rows = db.execute(
                    "SELECT record FROM reference_working.discovery_revisions WHERE space_id = %s AND discovery_id = %s ORDER BY version",
                    (self.store.space_id, discovery_id),
                ).fetchall()
                history = tuple(DiscoveryRevision.model_validate(row[0]) for row in rows)
                self.store._check_access(db, actor, (history, replacement))
                if not history or history[-1].version != expected_version:
                    raise VersionConflictError("discovery version changed")
                revision, working = prepare_discovery_decision(
                    history[-1],
                    actor_id=str(actor),
                    reason=reason,
                    action=action,
                    replacement=replacement,
                    work_id=work_id,
                )
                self.store._check_access(db, actor, (revision, working))
                if working is not None:
                    db.execute(
                        "INSERT INTO reference_working.heads VALUES (%s, %s, 1)",
                        (self.store.space_id, working.reference.id),
                    )
                    self.store._insert_revision(db, working)
                self._append(db, revision)
                return revision
        except psycopg.errors.UniqueViolation as exc:
            raise VersionConflictError("hypothesis ID already belongs to working history") from exc
