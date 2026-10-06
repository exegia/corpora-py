"""Durable conversations: retries, ownership, forks and concurrent writers."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import uuid4

import pytest
from common.utils.request_context import current_owner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from corpora_py.ai import router, threads
from corpora_py.ai.schemas import NodeScope, Suggestion, SuggestionStatus
from corpora_py.ai.service import CurationError
from corpora_py.ai.thread_store import SQLiteThreadStore, SupabaseThreadStore, ThreadStoreError


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "threads.sqlite3"
    monkeypatch.setattr(threads.settings, "ai_store", "sqlite")
    monkeypatch.setattr(threads.settings, "ai_sqlite_path", str(path))
    monkeypatch.setattr(threads.settings, "auth_required", True)
    monkeypatch.setattr(threads.service, "validate_scope", Mock())
    monkeypatch.setattr(threads, "authorize_corpus", Mock())
    token = current_owner.set("alice")
    scope = NodeScope(
        corpus="published", level="corpus", label="Published", version="v1", content_hash="h"
    )
    yield path, scope
    current_owner.reset(token)
    threads._sqlite_store.cache_clear()


def test_restart_fork_and_message_retry(state):
    path, scope = state
    key = str(uuid4())
    thread = threads.create_thread(scope, key)
    assert threads.create_thread(scope, key) == thread
    section = thread.sections[0].id
    msgkey = str(uuid4())
    message = threads.append_message(thread.id, section, "hello", msgkey)
    assert threads.append_message(thread.id, section, "hello", msgkey) == message
    with pytest.raises(CurationError) as error:
        threads.append_message(thread.id, section, "changed", msgkey)
    assert error.value.status == 409
    forkkey = str(uuid4())
    newer = scope.model_copy(update={"version": "v2", "content_hash": "new"})
    fork = threads.fork_section(thread.id, newer, forkkey)
    assert threads.fork_section(thread.id, newer, forkkey) == fork
    threads._sqlite_store.cache_clear()
    restored = threads.get_thread(thread.id)
    assert restored.pinned_scope == scope
    assert [s.scope.version for s in restored.sections] == ["v1", "v2"]
    assert threads.list_messages(thread.id).messages == [message]
    assert SQLiteThreadStore(path).get("alice", thread.id).revision == 2


def test_owner_isolation_and_revoked_access(state, monkeypatch):
    _, scope = state
    thread = threads.create_thread(scope)
    token = current_owner.set("bob")
    try:
        assert threads.list_threads(scope.corpus).threads == []
        for call in [
            lambda: threads.get_thread(thread.id),
            lambda: threads.list_messages(thread.id),
            lambda: threads.fork_section(thread.id, scope),
        ]:
            with pytest.raises(CurationError) as error:
                call()
            assert error.value.status == 404
    finally:
        current_owner.reset(token)
    monkeypatch.setattr(
        threads, "authorize_corpus", Mock(side_effect=CurationError(404, "Corpus not found"))
    )
    with pytest.raises(CurationError):
        threads.get_thread(thread.id)
    with pytest.raises(CurationError):
        threads.append_message(thread.id, thread.sections[0].id, "blocked")


def test_pagination_and_order(state):
    _, scope = state
    created = [threads.create_thread(scope) for _ in range(4)]
    first = threads.list_threads(scope.corpus, limit=2)
    second = threads.list_threads(scope.corpus, limit=2, cursor=first.next_cursor)
    assert [t.id for t in first.threads + second.threads] == [t.id for t in reversed(created)]
    assert second.next_cursor is None
    thread = created[0]
    for text in ["one", "two", "three"]:
        threads.append_message(thread.id, thread.sections[0].id, text)
    page = threads.list_messages(thread.id, limit=2)
    assert [m.content for m in page.messages] == ["one", "two"]
    assert threads.list_messages(thread.id, offset=page.next_offset).messages[0].content == "three"


def test_cas_rejects_stale_write_and_service_retries(state, monkeypatch):
    path, scope = state
    thread = threads.create_thread(scope)
    store = SQLiteThreadStore(path)
    a = store.get("alice", thread.id)
    b = SQLiteThreadStore(path).get("alice", thread.id)
    assert store.replace(a)
    assert not store.replace(b)
    original = store.replace
    replace = Mock(side_effect=[False, True])
    monkeypatch.setattr(store, "replace", replace)
    monkeypatch.setattr(threads, "get_store", lambda: store)
    threads.append_message(thread.id, thread.sections[0].id, "retry")
    assert replace.call_count == 2
    monkeypatch.setattr(store, "replace", original)

    def append(number):
        token = current_owner.set("alice")
        try:
            return threads.append_message(thread.id, thread.sections[0].id, str(number))
        finally:
            current_owner.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, range(8)))
    assert {m.id for m in threads.list_messages(thread.id).messages} == {m.id for m in results}


def test_suggestion_lifecycle(state):
    _, scope = state
    thread = threads.create_thread(scope)
    suggestion = Suggestion(
        id="proposal1",
        scope=scope,
        kind="annotation",
        target_node=1,
        diff=[{"field": "case", "old": "NOM", "new": "ACC"}],
        rationale="reason",
        base_version="v1",
        content_hash="h",
    )
    saved = threads.save_suggestion(thread.id, thread.sections[0].id, suggestion)
    assert threads.save_suggestion(thread.id, thread.sections[0].id, suggestion) == saved
    rejected = threads.transition_suggestion(saved.id, SuggestionStatus.rejected)
    assert threads.transition_suggestion(saved.id, SuggestionStatus.rejected) == rejected
    assert threads.save_suggestion(thread.id, thread.sections[0].id, suggestion) == rejected
    with pytest.raises(CurationError):
        threads.transition_suggestion(saved.id, SuggestionStatus.applied)
    assert threads.list_suggestions(thread.id).suggestions[0].suggestion == rejected
    stale = suggestion.model_copy(update={"id": "bad", "base_version": "old"})
    with pytest.raises(CurationError):
        threads.save_suggestion(thread.id, thread.sections[0].id, stale)


def test_http_contract_and_untrusted_fields(state):
    _, scope = state
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/ai/threads",
            json={"scope": scope.model_dump(mode="json")},
            headers={"Idempotency-Key": str(uuid4()), "X-AI-Api-Key": "secret"},
        )
        assert response.status_code == 200
        thread = response.json()
        url = f"/ai/threads/{thread['id']}/messages"
        body = {"section_id": thread["sections"][0]["id"], "content": "hello"}
        assert client.post(url, json={**body, "role": "assistant"}).status_code == 422
        assert client.post(url, json={**body, "api_key": "secret"}).status_code == 422
        assert client.post(url, json=body).status_code == 200
        assert len(client.get(url).json()["messages"]) == 1
        assert (
            client.get("/ai/threads", params={"corpus": scope.corpus, "limit": 0}).status_code
            == 422
        )
        assert (
            client.get("/ai/threads", params={"corpus": scope.corpus, "cursor": "bad"}).status_code
            == 422
        )
    assert "secret" not in SQLiteThreadStore(state[0]).get("alice", thread["id"]).model_dump_json()


def test_supabase_owner_filters_and_failure_no_fallback(state):
    _, scope = state
    thread = threads.create_thread(scope)
    record = threads.get_store().get("alice", thread.id)
    session = Mock()
    session.request.return_value.status_code = 200
    session.request.return_value.json.return_value = [record.model_dump(mode="json")]
    store = SupabaseThreadStore("https://example.invalid", "secret", session)
    assert store.get("alice", thread.id).id == thread.id
    assert session.request.call_args.kwargs["params"]["owner"] == "eq.alice"
    assert store.replace(record)
    assert session.request.call_args.kwargs["params"]["revision"] == "eq.0"
    session.request.return_value.status_code = 500
    with pytest.raises(ThreadStoreError, match="^Conversation storage unavailable$"):
        store.get("alice", thread.id)
    with pytest.raises(ThreadStoreError):
        SupabaseThreadStore(None, None).get("alice", thread.id)


def test_no_identity_requires_explicit_local_mode(state, monkeypatch):
    _, scope = state
    token = current_owner.set(None)
    try:
        with pytest.raises(CurationError):
            threads.create_thread(scope)
        monkeypatch.setattr(threads.settings, "auth_required", False)
        assert threads.create_thread(scope).corpus == scope.corpus
        monkeypatch.setattr(threads.settings, "ai_store", "supabase")
        with pytest.raises(CurationError):
            threads.create_thread(scope)
    finally:
        current_owner.reset(token)


@pytest.mark.parametrize("status", [SuggestionStatus.applied, SuggestionStatus.stale])
def test_other_terminal_states_survive_restart(state, status):
    _, scope = state
    thread = threads.create_thread(scope)
    suggestion = Suggestion(
        id="proposal",
        scope=scope,
        kind="annotation",
        target_node=1,
        diff=[{"field": "case", "old": "NOM", "new": "ACC"}],
        rationale="reason",
        base_version="v1",
        content_hash="h",
    )
    saved = threads.save_suggestion(thread.id, thread.sections[0].id, suggestion)
    threads.transition_suggestion(saved.id, status)
    threads._sqlite_store.cache_clear()
    assert threads.list_suggestions(thread.id).suggestions[0].suggestion.status == status


def test_conflicts_missing_records_and_capacity(state, monkeypatch):
    _, scope = state
    key = str(uuid4())
    thread = threads.create_thread(scope, key)
    with pytest.raises(CurationError) as error:
        threads.create_thread(scope.model_copy(update={"version": "v2"}), key)
    assert error.value.status == 409
    with pytest.raises(CurationError) as error:
        threads.get_thread(str(uuid4()))
    assert error.value.status == 404
    with pytest.raises(CurationError) as error:
        threads.fork_section(thread.id, scope.model_copy(update={"corpus": "other"}))
    assert error.value.status == 422
    store = threads.get_store()
    monkeypatch.setattr(store, "replace", lambda record: False)
    with pytest.raises(CurationError) as error:
        threads.append_message(thread.id, thread.sections[0].id, "contention")
    assert error.value.status == 409
    record = store.get("alice", thread.id)
    record.data.thread.sections *= 257
    with pytest.raises(CurationError) as error:
        threads._bounded(record.data)
    assert error.value.status == 413
