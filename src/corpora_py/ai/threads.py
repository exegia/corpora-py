"""Owned conversation state. No corpus writes or model credentials live here."""

from __future__ import annotations

import base64
import json
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from common.utils.config import settings
from common.utils.request_context import current_owner
from platformdirs import user_data_path

from . import service
from .schemas import (
    MessageListResponse,
    NodeScope,
    Suggestion,
    SuggestionListResponse,
    SuggestionStatus,
    Thread,
    ThreadListResponse,
    ThreadMessage,
    ThreadSection,
    ThreadSuggestion,
)
from .service import CurationError
from .thread_store import (
    SQLiteThreadStore,
    SupabaseThreadStore,
    ThreadRecord,
    ThreadState,
    ThreadStore,
)


@lru_cache(maxsize=4)
def _sqlite_store(path: str) -> SQLiteThreadStore:
    return SQLiteThreadStore(path)


def get_store() -> ThreadStore:
    if settings.ai_store == "sqlite":
        path = settings.ai_sqlite_path or str(user_data_path("corpora") / "ai-threads.sqlite3")
        return _sqlite_store(path)
    return SupabaseThreadStore(settings.supabase_api_url, settings.supabase_service_role_key)


def _owner() -> str:
    owner = current_owner.get()
    if owner:
        return owner
    if not settings.auth_required and settings.ai_store == "sqlite":
        return "local"
    raise CurationError(403, "Verified identity required for conversation storage")


def _id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise CurationError(404, "Conversation record not found") from exc


def _operation_id(namespace: str, key: str | None) -> str:
    if key is None:
        return str(uuid4())
    try:
        normalized = str(UUID(key))
    except ValueError as exc:
        raise CurationError(422, "Idempotency-Key must be a UUID") from exc
    return str(uuid5(NAMESPACE_URL, namespace + ":" + normalized))


def authorize_corpus(corpus: str) -> None:
    """Recheck current access without requiring a historical pin to be current."""
    try:
        with tempfile.TemporaryDirectory(prefix="corpora-ai-access-") as temporary:
            service._archive(corpus, Path(temporary))
    except service.storage.CorpusNotFoundError as exc:
        raise CurationError(404, "Corpus not found") from exc
    except (service.storage.StorageError, service.jobs.JobStoreError, OSError) as exc:
        raise CurationError(503, "Corpus storage is unavailable") from exc


def _record(store: ThreadStore, owner: str, thread_id: str) -> ThreadRecord:
    record = store.get(owner, _id(thread_id))
    if record is None:
        raise CurationError(404, "Thread not found")
    return record


def _bounded(state: ThreadState) -> None:
    if (
        len(state.thread.sections) > 256
        or len(state.messages) > 2048
        or len(state.suggestions) > 512
        or len(state.model_dump_json().encode("utf-8")) > 2_000_000
    ):
        raise CurationError(413, "Thread capacity reached; start a new thread")


def _update(thread_id: str, change: Callable[[ThreadState], None]) -> ThreadState:
    owner, store = _owner(), get_store()
    first = _record(store, owner, thread_id)
    authorize_corpus(first.corpus)
    for attempt in range(5):
        record = first if attempt == 0 else _record(store, owner, thread_id)
        before = record.data.model_dump_json()
        change(record.data)
        _bounded(record.data)
        if before == record.data.model_dump_json() or store.replace(record):
            return record.data
    raise CurationError(409, "Thread changed concurrently; retry with the same Idempotency-Key")


def create_thread(scope: NodeScope, key: str | None = None) -> Thread:
    owner, store = _owner(), get_store()
    thread_id = _operation_id("thread:" + owner, key)
    existing = store.get(owner, thread_id)
    if existing:
        authorize_corpus(existing.corpus)
        if existing.data.thread.pinned_scope != scope:
            raise CurationError(409, "Idempotency-Key was already used with another scope")
        return existing.data.thread
    service.validate_scope(scope)
    now = datetime.now(UTC)
    thread = Thread(
        id=thread_id,
        corpus=scope.corpus,
        pinned_scope=scope,
        sections=[
            ThreadSection(id=str(uuid5(UUID(thread_id), "root")), scope=scope, created_at=now)
        ],
        created_at=now,
    )
    record = ThreadRecord(
        id=thread_id,
        owner=owner,
        corpus=scope.corpus,
        created_at=now.isoformat(),
        data=ThreadState(thread=thread),
    )
    _bounded(record.data)
    if store.create(record):
        return thread
    existing = _record(store, owner, thread_id)
    if existing.data.thread.pinned_scope != scope:
        raise CurationError(409, "Idempotency-Key was already used with another scope")
    return existing.data.thread


def get_thread(thread_id: str) -> Thread:
    record = _record(get_store(), _owner(), thread_id)
    authorize_corpus(record.corpus)
    return record.data.thread


def list_threads(corpus: str, limit: int = 50, cursor: str | None = None) -> ThreadListResponse:
    owner, store = _owner(), get_store()
    authorize_corpus(corpus)
    before = None
    if cursor:
        try:
            timestamp, thread_id = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None:
                raise ValueError("Timezone required")
            before = (parsed.astimezone(UTC).isoformat(), str(UUID(thread_id)))
        except (ValueError, TypeError, UnicodeError) as exc:
            raise CurationError(422, "Invalid thread cursor") from exc
    rows = store.list(owner, corpus, limit + 1, before)
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([last.created_at, last.id]).encode()
        ).decode()
    return ThreadListResponse(threads=[row.data.thread for row in page], next_cursor=next_cursor)


def fork_section(thread_id: str, scope: NodeScope, key: str | None = None) -> Thread:
    section_id = _operation_id("section:" + _id(thread_id), key)

    def change(state: ThreadState) -> None:
        if scope.corpus != state.thread.corpus:
            raise CurationError(422, "A section must stay in its thread's corpus")
        existing = next((s for s in state.thread.sections if s.id == section_id), None)
        if existing:
            if existing.scope != scope:
                raise CurationError(409, "Idempotency-Key was already used with another scope")
            return
        service.validate_scope(scope)
        state.thread.sections.append(
            ThreadSection(id=section_id, scope=scope, created_at=datetime.now(UTC))
        )

    return _update(thread_id, change).thread


def append_message(
    thread_id: str,
    section_id: str,
    content: str,
    key: str | None = None,
    *,
    role: Literal["user", "assistant", "tool"] = "user",
) -> ThreadMessage:
    """Trusted chat code can persist assistant/tool roles; HTTP exposes only user."""
    message = ThreadMessage(
        id=_operation_id("message:" + _id(thread_id), key),
        section_id=_id(section_id),
        role=role,
        content=content,
        created_at=datetime.now(UTC),
    )

    def change(state: ThreadState) -> None:
        if not any(s.id == message.section_id for s in state.thread.sections):
            raise CurationError(404, "Thread section not found")
        existing = next((m for m in state.messages if m.id == message.id), None)
        if existing:
            if (existing.content, existing.section_id, existing.role) != (
                message.content,
                message.section_id,
                message.role,
            ):
                raise CurationError(409, "Idempotency-Key was already used with another message")
            return
        state.messages.append(message)

    state = _update(thread_id, change)
    return next(m for m in state.messages if m.id == message.id)


def list_messages(thread_id: str, limit: int = 50, offset: int = 0) -> MessageListResponse:
    record = _record(get_store(), _owner(), thread_id)
    authorize_corpus(record.corpus)
    messages = record.data.messages
    end = offset + limit
    return MessageListResponse(
        messages=messages[offset:end], next_offset=end if end < len(messages) else None
    )


def save_suggestion(thread_id: str, section_id: str, suggestion: Suggestion) -> Suggestion:
    """Internal producer API; clients cannot submit model-generated suggestions.

    IDs are thread-qualified, so rejection can resolve ownership without
    scanning every conversation. The producer must use the returned ID.
    """
    thread_id, section_id = _id(thread_id), _id(section_id)
    prefix = thread_id + ":"
    if suggestion.id.startswith(prefix):
        suggestion_id = prefix + _id(suggestion.id[len(prefix) :])
    else:
        suggestion_id = prefix + str(uuid5(UUID(thread_id), suggestion.id))
    proposed = suggestion.model_copy(update={"id": suggestion_id}, deep=True)
    if proposed.status is not SuggestionStatus.pending:
        raise CurationError(422, "New suggestions must be pending")

    def change(state: ThreadState) -> None:
        section = next((s for s in state.thread.sections if s.id == section_id), None)
        if section is None:
            raise CurationError(404, "Thread section not found")
        if (
            proposed.scope != section.scope
            or proposed.base_version != section.scope.version
            or not proposed.content_hash
            or (
                section.scope.content_hash is not None
                and proposed.content_hash != section.scope.content_hash
            )
        ):
            raise CurationError(409, "Suggestion must match the pinned section version and scope")
        existing = next((s for s in state.suggestions if s.suggestion.id == suggestion_id), None)
        if existing:
            original = existing.suggestion.model_copy(update={"status": SuggestionStatus.pending})
            if original != proposed or existing.section_id != section_id:
                raise CurationError(409, "Suggestion ID was already used with another payload")
            return
        state.suggestions.append(
            ThreadSuggestion(
                section_id=section_id, suggestion=proposed, created_at=datetime.now(UTC)
            )
        )

    state = _update(thread_id, change)
    return next(s.suggestion for s in state.suggestions if s.suggestion.id == suggestion_id)


def transition_suggestion(suggestion_id: str, status: SuggestionStatus) -> Suggestion:
    """Internal lifecycle hook. 'applied' is only for the future WAL service.

    HTTP only exposes rejection. Repeating a terminal transition is idempotent;
    changing one terminal state to another is a conflict.
    """
    parts = suggestion_id.split(":")
    if len(parts) != 2:
        raise CurationError(404, "Suggestion not found")
    thread_id = _id(parts[0])
    suggestion_id = thread_id + ":" + _id(parts[1])
    if status is SuggestionStatus.pending:
        raise CurationError(409, "Cannot reopen a suggestion")

    def change(state: ThreadState) -> None:
        row = next((s for s in state.suggestions if s.suggestion.id == suggestion_id), None)
        if row is None:
            raise CurationError(404, "Suggestion not found")
        if row.suggestion.status not in (SuggestionStatus.pending, status):
            raise CurationError(409, "Suggestion is already in another terminal state")
        row.suggestion.status = status

    state = _update(thread_id, change)
    return next(s.suggestion for s in state.suggestions if s.suggestion.id == suggestion_id)


def list_suggestions(thread_id: str, limit: int = 50, offset: int = 0) -> SuggestionListResponse:
    record = _record(get_store(), _owner(), thread_id)
    authorize_corpus(record.corpus)
    end = offset + limit
    return SuggestionListResponse(
        suggestions=record.data.suggestions[offset:end],
        next_offset=end if end < len(record.data.suggestions) else None,
    )
