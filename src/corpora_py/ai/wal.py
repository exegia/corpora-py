"""Write-ahead apply/undo protocol for a conditional, receipt-bearing draft store.

The hosted HTTP/MCP service uses a draft adapter that atomically compares
revisions and retains a publication receipt. A
process lock or an unconditional archive upload cannot satisfy that contract.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from .schemas import DiffRow, ScopeLevel, Suggestion, SuggestionStatus, VersionHistoryEntry
from .service import CurationError


class Evidence(BaseModel):
    """Adapter-produced evidence; revision must never be reused (including undo).

    digest covers the entire draft, including features and provenance, rather
    than just rendered text. content_hash is the selected scope's text hash.
    values contains all fields on the target node, including absent values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    revision: str = Field(min_length=1)
    digest: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    values: dict[str, str | None]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    before: Evidence
    after: Evidence


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    owner: str
    suggestion: Suggestion
    plan: Plan
    created_at: datetime
    reverts: str | None = None

    @property
    def proof(self) -> str:
        """Bind the durable receipt to this exact intent and both snapshots."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def entries(self, applied_at: datetime) -> list[VersionHistoryEntry]:
        return [
            VersionHistoryEntry(
                change_id=str(uuid5(NAMESPACE_URL, self.id + ":" + row.field)),
                operation_id=self.id,
                corpus=self.suggestion.scope.corpus,
                version=self.plan.after.version,
                node_id=self.suggestion.target_node,
                field=row.field,
                previous_value=row.old,
                new_value=row.new,
                resp=["#corpora-ai", "#" + self.owner],
                applied_by=self.owner,
                applied_at=applied_at,
                reverts=(
                    str(uuid5(NAMESPACE_URL, self.reverts + ":" + row.field))
                    if self.reverts
                    else None
                ),
            )
            for row in self.suggestion.diff
        ]


class Receipt(BaseModel):
    proof: str
    applied_at: datetime


class Record(BaseModel):
    intent: Intent
    applied_at: datetime | None = None


class Journal(Protocol):
    """Durable, owner-filtered operations; insert and finish must be atomic.

    insert returns the stored record on ID conflict, without replacing it.
    finish is idempotent and preserves the first successful applied timestamp.
    A production adapter maps field entries to existing corpus_changes rows as
    one transaction, with stable IDs and a persisted group/receipt binding.
    """

    def get(self, owner: str, operation_id: str) -> Record | None: ...
    def insert(self, intent: Intent) -> Record: ...
    def finish(self, owner: str, operation_id: str, applied_at: datetime) -> Record: ...


class Drafts(Protocol):
    """Production adapter obligations, not optional optimizations.

    authorize must check current caller write permission and reject published or
    locked corpora (423). confirm must validate corpus-wide confirmation bound
    to owner, suggestion and pinned version; merely nonempty is insufficient.
    prepare must resolve the owned document, validate target membership in the
    pinned scope, reject unsupported fields/types, and stage immutable output
    with version/history/provenance before returning evidence. It cannot publish.

    commit must atomically compare the *entire* before evidence, recheck write
    authorization/locks, publish the staged after state AND retain intent.proof
    as a durable receipt. Every writer must participate in the same revision
    protocol. False means definitely not published; exceptions are ambiguous.
    Receipts must survive subsequent edits and undo; they cannot be inferred
    from the current hash. All methods must scope lookups to the verified owner.
    """

    def authorize(self, owner: str, corpus: str) -> None: ...
    def confirm(self, owner: str, suggestion: Suggestion, token: str | None) -> None: ...
    def prepare(self, owner: str, suggestion: Suggestion) -> Plan: ...
    def read(self, intent: Intent) -> Evidence: ...
    def receipt(self, intent: Intent) -> Receipt | None: ...
    def commit(self, intent: Intent) -> bool: ...


class Recovery(BaseModel):
    state: Literal["applied", "not_applied", "conflict"]
    record: Record


def _operation_id(owner: str, suggestion_id: str, reverts: str | None) -> str:
    # JSON avoids ambiguous delimiter concatenation for opaque suggestion IDs.
    return str(uuid5(NAMESPACE_URL, json.dumps(["ai-change", owner, suggestion_id, reverts])))


def _validate_plan(suggestion: Suggestion, plan: Plan) -> None:
    before, after = plan.before, plan.after
    if (
        before.version.removeprefix("v") != suggestion.base_version.removeprefix("v")
        or suggestion.scope.version.removeprefix("v") != before.version.removeprefix("v")
        or before.content_hash != suggestion.content_hash
        or (
            suggestion.scope.content_hash is not None
            and before.content_hash != suggestion.scope.content_hash
        )
    ):
        raise CurationError(409, "Suggestion version or content is stale")
    fields = [row.field for row in suggestion.diff]
    if len(set(fields)) != len(fields) or any(not field for field in fields):
        raise CurationError(422, "A change must name each field exactly once")
    expected = dict(before.values)
    for row in suggestion.diff:
        if row.old == row.new:
            raise CurationError(422, "A change must alter every listed field")
        if row.field not in before.values or before.values[row.field] != row.old:
            raise CurationError(409, "Displaced feature value is stale")
        expected[row.field] = row.new
    if after.values != expected:
        raise CurationError(422, "Prepared draft does not match the complete requested diff")
    if (
        before.revision == after.revision
        or before.digest == after.digest
        or before.version.removeprefix("v") == after.version.removeprefix("v")
    ):
        raise CurationError(422, "Prepared draft must have new revision, digest and version")


class MutationEngine:
    def __init__(self, journal: Journal, drafts: Drafts):
        self.journal, self.drafts = journal, drafts

    def apply(self, owner: str, suggestion: Suggestion, confirmation: str | None = None) -> Record:
        """Caller must resolve the suggestion through the owned thread service."""
        return self._apply(owner, suggestion, confirmation, reverts=None)

    def _apply(
        self,
        owner: str,
        suggestion: Suggestion,
        confirmation: str | None,
        *,
        reverts: str | None,
        expected_before: Evidence | None = None,
    ) -> Record:
        if not owner:
            raise CurationError(403, "Verified identity required")
        self.drafts.authorize(owner, suggestion.scope.corpus)
        operation_id = _operation_id(owner, suggestion.id, reverts)
        existing = self.journal.get(owner, operation_id)
        if existing:
            # Terminal suggestion state may have changed after the first apply.
            normalized = suggestion.model_copy(update={"status": existing.intent.suggestion.status})
            if existing.intent.suggestion != normalized or existing.intent.reverts != reverts:
                raise CurationError(409, "Operation ID was already used with another payload")
            if existing.applied_at is not None:
                return existing
        if suggestion.status is not SuggestionStatus.pending:
            if existing is not None:
                recovered = self.reconcile(owner, operation_id)
                if recovered.state == "applied":
                    return recovered.record
            raise CurationError(409, "Only pending suggestions can be applied")
        if suggestion.scope.level is ScopeLevel.corpus:
            self.drafts.confirm(owner, suggestion, confirmation)
        if existing is None:
            try:
                plan = self.drafts.prepare(owner, suggestion)
                _validate_plan(suggestion, plan)
            except CurationError as exc:
                # Another identical request can insert and commit between our
                # first journal lookup and staging. Recover its durable intent.
                raced = self.journal.get(owner, operation_id) if exc.status == 409 else None
                if (
                    raced is None
                    or raced.intent.suggestion != suggestion
                    or raced.intent.reverts != reverts
                ):
                    raise
                return self._resume(raced)
            if expected_before is not None and plan.before != expected_before:
                raise CurationError(
                    409, "Draft changed since apply; undo cannot overwrite intervening edits"
                )
            intent = Intent(
                id=operation_id,
                owner=owner,
                suggestion=suggestion,
                plan=plan,
                created_at=datetime.now(UTC),
                reverts=reverts,
            )
            existing = self.journal.insert(intent)  # MUST complete before commit.
            if existing.intent.suggestion != suggestion or existing.intent.reverts != reverts:
                raise CurationError(409, "Concurrent operation has another payload")
        return self._resume(existing)

    def _resume(self, record: Record) -> Record:
        outcome = self.reconcile(record.intent.owner, record.intent.id)
        if outcome.state == "applied":
            return outcome.record
        if outcome.state == "conflict":
            raise CurationError(409, "Pending change conflicts with the draft; recovery required")
        # A concurrent writer may win after read. Only the adapter's atomic CAS
        # can authorize publication; never rely on a process-local lock.
        self.drafts.commit(record.intent)
        outcome = self.reconcile(record.intent.owner, record.intent.id)
        if outcome.state != "applied":
            raise CurationError(409, "Draft was not committed; retry or recover the pending change")
        return outcome.record

    def reconcile(self, owner: str, operation_id: str) -> Recovery:
        record = self.journal.get(owner, operation_id)
        if record is None:
            raise CurationError(404, "Change not found")
        intent = record.intent
        self.drafts.authorize(owner, intent.suggestion.scope.corpus)
        if record.applied_at is not None:
            return Recovery(state="applied", record=record)
        # Read HEAD before the receipt: a concurrent atomic publication seen
        # by read must also be visible to the subsequent receipt lookup.
        current = self.drafts.read(intent)
        receipt = self.drafts.receipt(intent)
        if receipt is not None and receipt.proof == intent.proof:
            # The durable receipt proves the exact atomic before->after change,
            # even if later edits have advanced HEAD while finalization failed.
            result = self.journal.finish(owner, intent.id, receipt.applied_at)
            return Recovery(state="applied", record=result)
        if receipt is not None:
            return Recovery(state="conflict", record=record)
        state: Literal["not_applied", "conflict"] = (
            "not_applied" if current == intent.plan.before else "conflict"
        )
        # Even an exact after snapshot without a receipt is ambiguous. Keep the
        # pending intent for explicit recovery, never claim success by difference.
        return Recovery(state=state, record=record)

    def undo(self, owner: str, operation_id: str, confirmation: str | None = None) -> Record:
        original = self.journal.get(owner, operation_id)
        if original is None:
            raise CurationError(404, "Change not found")
        if original.applied_at is None:
            raise CurationError(409, "Recover the pending change before undo")
        intent = original.intent
        scope = intent.suggestion.scope.model_copy(
            update={
                "version": intent.plan.after.version,
                "content_hash": intent.plan.after.content_hash,
            }
        )
        inverse = intent.suggestion.model_copy(
            update={
                "id": "undo:" + intent.id,
                "scope": scope,
                "base_version": intent.plan.after.version,
                "content_hash": intent.plan.after.content_hash,
                "status": SuggestionStatus.pending,
                "diff": [
                    DiffRow(field=r.field, old=r.new, new=r.old) for r in intent.suggestion.diff
                ],
            },
            deep=True,
        )
        return self._apply(
            owner, inverse, confirmation, reverts=intent.id, expected_before=intent.plan.after
        )
