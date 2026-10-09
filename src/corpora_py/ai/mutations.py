"""Owned HTTP/MCP mutations over explicitly provisioned hosted drafts."""

from __future__ import annotations

from common.utils.config import settings
from common.utils.request_context import current_owner

from . import threads
from .archive_editor import ArchiveDrafts
from .schemas import (
    ApplyResponse,
    ChangeLogResponse,
    ErrorInfo,
    SuggestionStatus,
    UndoResponse,
    VersionHistoryEntry,
)
from .service import CurationError
from .wal import MutationEngine, Record
from .wal_sqlite import JournalUnavailableError
from .wal_supabase import HostedStorage, SupabaseJournal, _parse, _uuid


def error_body(exc: CurationError) -> dict:
    """Preserve the panel's frozen degradation shapes on both transports."""
    codes = {
        403: "forbidden",
        409: "stale",
        423: "locked",
        428: "confirmation_required",
        503: "model_unavailable",
    }
    if exc.status not in codes or "code" in exc.body:
        return exc.body
    return ErrorInfo.model_validate(
        {
            "code": codes[exc.status],
            "reason": exc.body["detail"],
            "retryable": exc.status == 503,
        }
    ).model_dump(mode="json")


def get_storage() -> HostedStorage:
    return HostedStorage(settings.supabase_api_url, settings.supabase_service_role_key)


def _context() -> tuple[str, HostedStorage, MutationEngine]:
    if not settings.ai_mutations_enabled:
        raise CurationError(501, "Hosted AI mutations are not enabled (corpora-py#214)")
    owner = current_owner.get()
    if not owner:
        raise CurationError(403, "Verified identity required for mutations")
    if settings.ai_store != "supabase":
        raise CurationError(503, "Mutations require hosted conversation storage")
    owner = _uuid(owner)
    storage = get_storage()
    try:
        capability = storage.rpc("capabilities", owner, {})
    except CurationError as exc:
        raise JournalUnavailableError("Mutation database migration is unavailable") from exc
    if not isinstance(capability, dict) or capability.get("mutation_api") != 1:
        raise JournalUnavailableError("Mutation database migration is unavailable")
    return owner, storage, MutationEngine(SupabaseJournal(storage), ArchiveDrafts(storage))


def _completed(storage: HostedStorage, owner: str, record: Record) -> Record:
    """Recover a lost finalization response using only the durable receipt.

    This does not edit HEAD and remains valid after publication locks a draft.
    """
    if record.applied_at is None:
        receipt = storage.receipt(owner, record.intent.id)
        if receipt is not None:
            if receipt.proof != record.intent.proof:
                raise CurationError(409, "Publication receipt conflicts with change")
            return SupabaseJournal(storage).finish(owner, record.intent.id, receipt.applied_at)
    return record


def apply(suggestion_id: str, confirmation: str | None = None) -> ApplyResponse:
    owner, storage, engine = _context()
    parts = suggestion_id.split(":")
    if len(parts) != 2:
        raise CurationError(404, "Suggestion not found")
    thread_id, local_id = (_uuid(part) for part in parts)
    suggestion_id = thread_id + ":" + local_id
    thread = threads._record(threads.get_store(), owner, thread_id)
    row = next((s for s in thread.data.suggestions if s.suggestion.id == suggestion_id), None)
    if row is None or row.suggestion.scope.corpus != thread.corpus:
        raise CurationError(404, "Suggestion not found")
    # The owner-scoped registry is authoritative for current draft access. The
    # publication RPC rechecks this stored payload and status under a row lock.
    storage.resolve(owner, thread.corpus)
    record = engine.apply(owner, row.suggestion, confirmation)
    if record.applied_at is None:
        raise JournalUnavailableError("Change finalization is unavailable")
    entries = record.intent.entries(record.applied_at)
    return ApplyResponse(
        suggestion_id=suggestion_id,
        status=SuggestionStatus.applied,
        change=entries[0],
        changes=entries,
        operation_id=record.intent.id,
    )


def undo(change_id: str) -> UndoResponse:
    owner, storage, engine = _context()
    change_id = _uuid(change_id)
    value = storage.rpc("change", owner, {"id": change_id})
    if value is None:
        raise CurationError(404, "Change not found")
    original = _parse(Record, value)
    if original.intent.owner != owner:
        raise JournalUnavailableError("Change storage unavailable")
    storage.resolve(owner, original.intent.suggestion.scope.corpus)
    original = _completed(storage, owner, original)
    record = engine.undo(owner, original.intent.id)
    if record.applied_at is None:
        raise JournalUnavailableError("Change finalization is unavailable")
    entries = record.intent.entries(record.applied_at)
    selected = next((entry for entry in entries if entry.reverts == change_id), None)
    if selected is None:
        raise JournalUnavailableError("Change storage returned an invalid group")
    return UndoResponse(
        reverted_change_id=change_id,
        revert=selected,
        reverts=entries,
        operation_id=record.intent.id,
    )


def history(
    corpus: str, node_id: int | None = None, limit: int = 50, offset: int = 0
) -> ChangeLogResponse:
    owner, storage, _ = _context()
    if not 1 <= limit <= 100 or offset < 0 or (node_id is not None and node_id < 1):
        raise CurationError(422, "Invalid history pagination or node")
    rows = storage.rpc(
        "history",
        owner,
        {"corpus": corpus, "node_id": node_id, "limit": limit + 1, "offset": offset},
    )
    if not isinstance(rows, list):
        raise JournalUnavailableError("Change storage unavailable")
    entries = [_parse(VersionHistoryEntry, row) for row in rows]
    if any(entry.applied_by != owner or entry.corpus != corpus for entry in entries):
        raise JournalUnavailableError("Change storage unavailable")
    return ChangeLogResponse(
        corpus=corpus,
        entries=entries[:limit],
        next_offset=offset + limit if len(entries) > limit else None,
    )
