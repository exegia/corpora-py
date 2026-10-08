"""Offline scholarly discovery persistence and audited work selection."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from corpora_linking import (
    Catalog,
    CitationDiscovery,
    ConversionMapping,
    TextLocator,
    TextSnapshot,
    identify_scholarly_citation,
    normalize_text,
    verify_text_anchor,
)
from corpora_linking.models import NonEmpty, Value
from pydantic import Field, model_validator

from .linking_conversion import ConversionInput, ConvertedReference
from .linking_store import SQLiteReferenceStore, VersionConflictError, WorkingRevision


class DiscoveryRevision(Value):
    version: int = Field(ge=1, strict=True)
    action: Literal["register", "identify", "select", "reject"]
    actor_id: NonEmpty
    reason: NonEmpty
    recorded_at: datetime
    discovery: CitationDiscovery
    mappings: tuple[ConversionMapping, ...] = ()
    selected_reference_id: UUID | None = None

    @model_validator(mode="after")
    def selection(self) -> "DiscoveryRevision":
        for mapping in self.mappings:
            if (
                mapping.converted.model_copy(update={"locators": ()})
                != self.discovery.source.model_copy(update={"locators": ()})
                or len(mapping.converted.locators) != 1
                or not isinstance(mapping.converted.locators[0], TextLocator)
                or mapping.converted.locators[0].stream_id
                != self.discovery.mention.selection.stream_id
            ):
                raise ValueError("discovery mappings require the same converted source stream")
        if self.action == "select":
            if self.selected_reference_id not in {ref.id for ref in self.discovery.hypotheses}:
                raise ValueError("selection must retain an identified hypothesis ID")
        elif self.selected_reference_id is not None:
            raise ValueError("only work selection may identify a working reference")
        return self


class SQLiteDiscoveryStore:
    """Same local database as working References; no authentication or deployment.

    Actors are trusted as in SQLiteReferenceStore. Registration retries reuse the
    original IDs; explicit catalog refresh and reviewer choice append CAS history.
    """

    def __init__(self, store: SQLiteReferenceStore, *, authority_id: str):
        if not hasattr(store, "path"):
            raise ValueError("discovery storage requires a local SQLite reference store")
        if not authority_id.strip():
            raise ValueError("authority_id is required")
        self.store = store
        self.authority_id = authority_id
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS linking_discovery_revisions (discovery_id TEXT NOT NULL, version INTEGER NOT NULL, record TEXT NOT NULL, PRIMARY KEY(discovery_id, version))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS linking_discovery_events (authority_id TEXT NOT NULL, event_id TEXT NOT NULL, discovery_id TEXT NOT NULL, digest TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(authority_id, event_id))"
            )

    def history(self, discovery_id: UUID) -> tuple[DiscoveryRevision, ...]:
        with closing(sqlite3.connect(self.store.path)) as db:
            rows = db.execute(
                "SELECT record FROM linking_discovery_revisions WHERE discovery_id = ? ORDER BY version",
                (str(discovery_id),),
            ).fetchall()
        return tuple(DiscoveryRevision.model_validate_json(row[0]) for row in rows)

    def get(self, discovery_id: UUID) -> CitationDiscovery | None:
        history = self.history(discovery_id)
        return history[-1].discovery if history else None

    @staticmethod
    def _verify(discovery: CitationDiscovery, snapshot: TextSnapshot) -> None:
        source = discovery.source.model_copy(update={"locators": ()})
        selector = discovery.mention.selection
        if source != snapshot.endpoint or selector.stream_id != snapshot.stream_id:
            raise ValueError("discovery belongs to another source snapshot")
        if normalize_text(snapshot.text, selector.normalization) != snapshot.text:
            raise ValueError("discovery normalization differs from pinned source")
        if (
            verify_text_anchor(
                selector,
                snapshot.text,
                expected_revision=source.revision or "",
                actual_revision=snapshot.endpoint.revision or "",
            )
            != "valid"
        ):
            raise ValueError("stale discovery source")

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
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT digest, record FROM linking_discovery_events WHERE authority_id = ? AND event_id = ?",
                (self.authority_id, str(event_id)),
            ).fetchone()
            if prior:
                if prior[0] != digest:
                    raise VersionConflictError("discovery event reused with changed evidence")
                return DiscoveryRevision.model_validate_json(prior[1])
            if db.execute(
                "SELECT 1 FROM linking_discovery_revisions WHERE discovery_id = ?",
                (str(discovery.id),),
            ).fetchone():
                raise VersionConflictError("discovery ID already belongs to history")
            revision = DiscoveryRevision(
                version=1,
                action="register",
                actor_id=self.store.actor_id,
                reason=reason,
                recorded_at=datetime.now(UTC),
                discovery=discovery,
                mappings=mappings,
            )
            self._insert(db, revision)
            db.execute(
                "INSERT INTO linking_discovery_events VALUES (?, ?, ?, ?, ?)",
                (
                    self.authority_id,
                    str(event_id),
                    str(discovery.id),
                    digest,
                    revision.model_dump_json(),
                ),
            )
            return revision

    @staticmethod
    def _insert(db: sqlite3.Connection, revision: DiscoveryRevision) -> None:
        db.execute(
            "INSERT INTO linking_discovery_revisions VALUES (?, ?, ?)",
            (str(revision.discovery.id), revision.version, revision.model_dump_json()),
        )

    def _current(
        self, db: sqlite3.Connection, discovery_id: UUID, expected_version: int
    ) -> DiscoveryRevision:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected version must be a positive integer")
        row = db.execute(
            "SELECT record FROM linking_discovery_revisions WHERE discovery_id = ? ORDER BY version DESC LIMIT 1",
            (str(discovery_id),),
        ).fetchone()
        current = DiscoveryRevision.model_validate_json(row[0]) if row else None
        if current is None or current.version != expected_version:
            raise VersionConflictError("discovery version changed")
        if current.action == "select":
            raise ValueError("selected discovery is retained; edit its working reference instead")
        return current

    def refresh_identification(
        self,
        discovery_id: UUID,
        snapshot: TextSnapshot,
        catalog: Catalog,
        *,
        expected_version: int,
        reason: str,
    ) -> DiscoveryRevision:
        history = self.history(discovery_id)
        if not history or history[-1].version != expected_version:
            raise VersionConflictError("discovery version changed")
        previous = history[-1].discovery
        self._verify(previous, snapshot)
        refreshed = identify_scholarly_citation(
            snapshot, previous.mention, catalog, provenance=previous.provenance
        )
        existing = {
            ref.target.work_id: ref.id
            for revision in history
            for ref in revision.discovery.hypotheses
        }
        refreshed = CitationDiscovery.model_validate(
            {
                **refreshed.model_dump(),
                "id": previous.id,
                "hypotheses": [
                    ref.model_copy(update={"id": existing.get(ref.target.work_id, ref.id)})
                    for ref in refreshed.hypotheses
                ],
            }
        )
        return self._transition(
            discovery_id,
            expected_version=expected_version,
            reason=reason,
            action="identify",
            replacement=refreshed,
        )

    def reject(
        self, discovery_id: UUID, *, expected_version: int, reason: str
    ) -> DiscoveryRevision:
        return self._transition(
            discovery_id, expected_version=expected_version, reason=reason, action="reject"
        )

    def select_work(
        self, discovery_id: UUID, work_id: str, *, expected_version: int, reason: str
    ) -> DiscoveryRevision:
        return self._transition(
            discovery_id,
            expected_version=expected_version,
            reason=reason,
            action="select",
            work_id=work_id,
        )

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
        if not reason.strip():
            raise ValueError("discovery decision reason is required")
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = self._current(db, discovery_id, expected_version)
            revision, working = prepare_discovery_decision(
                current,
                actor_id=self.store.actor_id,
                reason=reason,
                action=action,
                replacement=replacement,
                work_id=work_id,
            )
            if working is not None:
                if db.execute(
                    "SELECT 1 FROM linking_revisions WHERE reference_id = ?",
                    (str(working.reference.id),),
                ).fetchone():
                    raise VersionConflictError("hypothesis ID already belongs to working history")
                db.execute(
                    "INSERT INTO linking_revisions VALUES (?, ?, ?)",
                    (str(working.reference.id), working.version, working.model_dump_json()),
                )
            self._insert(db, revision)
            return revision


def prepare_discovery_registration(
    discovery: CitationDiscovery,
    snapshot: TextSnapshot,
    *,
    reason: str,
    mappings: tuple[ConversionMapping, ...],
) -> tuple[CitationDiscovery, tuple[ConversionMapping, ...], str]:
    discovery = CitationDiscovery.model_validate_json(discovery.model_dump_json())
    snapshot = TextSnapshot.model_validate(snapshot.model_dump())
    SQLiteDiscoveryStore._verify(discovery, snapshot)
    conversion = ConversionInput(converted=snapshot, mappings=mappings)
    if not reason.strip():
        raise ValueError("registration reason is required")
    semantic = discovery.model_dump(mode="json")
    del semantic["id"]
    for ref in semantic["hypotheses"]:
        del ref["id"]
    digest = hashlib.sha256(
        json.dumps(
            {"discovery": semantic, "conversion": conversion.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return discovery, conversion.mappings, digest


def prepare_discovery_decision(
    current: DiscoveryRevision,
    *,
    actor_id: str,
    reason: str,
    action: Literal["identify", "select", "reject"],
    replacement: CitationDiscovery | None = None,
    work_id: str | None = None,
) -> tuple[DiscoveryRevision, WorkingRevision | None]:
    """Shared decision rules after authorization and storage CAS."""
    if not reason.strip():
        raise ValueError("discovery decision reason is required")
    if current.action == "select":
        raise ValueError("selected discovery is retained; edit its working reference instead")
    if current.action == "reject" and action != "identify":
        raise ValueError("rejected discovery requires explicit fresh identification")
    discovery = replacement or current.discovery
    if (
        discovery.id != current.discovery.id
        or discovery.source != current.discovery.source
        or discovery.mention != current.discovery.mention
        or discovery.provenance != current.discovery.provenance
    ):
        raise ValueError("identification cannot replace discovery identity or source evidence")
    selected = None
    if action == "select":
        candidates = [ref for ref in discovery.hypotheses if ref.target.work_id == work_id]
        if len(candidates) != 1:
            raise ValueError("select an identified work; refresh unknown catalog evidence first")
        selected = candidates[0]
    revision = DiscoveryRevision(
        version=current.version + 1,
        action=action,
        actor_id=actor_id,
        reason=reason,
        recorded_at=datetime.now(UTC),
        discovery=discovery,
        mappings=current.mappings,
        selected_reference_id=selected.id if selected else None,
    )
    working = None
    if selected is not None:
        selector = discovery.mention.selection
        overlapping = tuple(
            mapping
            for mapping in current.mappings
            if isinstance(mapping.converted.locators[0], TextLocator)
            and mapping.converted.locators[0].start < selector.end
            and mapping.converted.locators[0].end > selector.start
        )
        conversion = (
            ConvertedReference(
                reference=selected,
                mappings=overlapping,
                diagnostics=("native bounds are retained evidence, not projected citation bounds",),
            )
            if current.mappings
            else None
        )
        working = WorkingRevision(
            version=1,
            action="edit",
            actor_id=actor_id,
            reason=reason,
            recorded_at=revision.recorded_at,
            reference=selected,
            conversion=conversion,
        )
    return revision, working
