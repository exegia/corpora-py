"""Public mutations using real archives, PostgreSQL transactions, HTTP and MCP."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from common.utils.request_context import current_owner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from test_ai_archive_editor import selection as selection
from test_ai_hosted_storage import DatabaseSession, literal
from test_ai_hosted_storage import postgres as postgres
from test_ai_service import archive as archive

from corpora_py import auth
from corpora_py.ai import mutations, router, service, threads
from corpora_py.ai.mcp import register_curation_tools
from corpora_py.ai.schemas import (
    DiffRow,
    ScopeLevel,
    SuggestionStatus,
    Thread,
    ThreadSection,
    ThreadSuggestion,
)
from corpora_py.ai.thread_store import ThreadRecord, ThreadState
from corpora_py.ai.wal_sqlite import JournalUnavailableError
from corpora_py.ai.wal_supabase import HostedStorage, SupabaseJournal


@pytest.fixture(scope="module")
def database(postgres):
    root = Path(__file__).resolve().parents[2] / "packages/admin/sql/migrations"
    postgres("CREATE TABLE auth.users(id uuid PRIMARY KEY);")
    postgres((root / "20260918141622_ai_thread_persistence.sql").read_text())
    postgres((root / "20260918165018_ai_mutation_api.sql").read_text())
    return postgres


class DatabaseThreads:
    def __init__(self, query):
        self.query = query

    def get(self, owner, thread_id):
        result = self.query(
            f"SET ROLE service_role; SELECT to_jsonb(t) FROM public.corpus_ai_threads t WHERE owner={literal(owner)}::uuid AND id={literal(thread_id)}::uuid;"
        ).stdout.strip()
        return ThreadRecord.model_validate_json(result) if result else None

    def replace(self, record):
        result = self.query(
            f"SET ROLE service_role; UPDATE public.corpus_ai_threads SET data={literal(record.data.model_dump_json())}::jsonb,revision=revision+1 WHERE owner={literal(record.owner)}::uuid AND id={literal(record.id)}::uuid AND revision={record.revision} RETURNING id;"
        )
        return bool(result.stdout.strip())


@pytest.fixture
def setup(database, archive, selection, tmp_path, monkeypatch):
    head, suggestion = selection
    thread_id, section_id = str(uuid4()), str(uuid4())
    suggestion.id = thread_id + ":" + str(uuid4())
    suggestion.diff.append(DiffRow(field="book", old=None, new="Appendix"))
    now = datetime.now(UTC)
    state = ThreadState(
        thread=Thread(
            id=thread_id,
            corpus=head.corpus,
            pinned_scope=suggestion.scope,
            sections=[ThreadSection(id=section_id, scope=suggestion.scope, created_at=now)],
            created_at=now,
        ),
        suggestions=[
            ThreadSuggestion(section_id=section_id, suggestion=suggestion, created_at=now)
        ],
    )
    database(
        f"INSERT INTO public.users VALUES ('{head.owner}'); INSERT INTO auth.users VALUES ('{head.owner}'); INSERT INTO public.corpus_documents VALUES ('{head.document_id}');"
    )
    database(
        f"INSERT INTO public.corpus_ai_threads(id,owner,corpus,created_at,data) VALUES ('{thread_id}','{head.owner}','mini',now(),{literal(state.model_dump_json())}::jsonb);"
    )
    storage = HostedStorage("https://local.invalid", "test-key", DatabaseSession(database))
    objects = {head.object_key: archive.read_bytes()}

    def verify(draft, key, digest):
        from corpora_py.ai.archive_editor import digest as file_digest

        path = tmp_path / (str(uuid4()) + ".corpus")
        path.write_bytes(objects[key])
        assert file_digest(path) == digest

    def download(draft, destination):
        destination.write_bytes(objects[draft.object_key])
        verify(draft, draft.object_key, draft.digest)

    def stage(draft, revision, path, digest):
        key = draft.key_for(revision)
        assert key not in objects
        objects[key] = path.read_bytes()
        verify(draft, key, digest)
        return key

    monkeypatch.setattr(storage, "verify_object", verify)
    monkeypatch.setattr(storage, "download", download)
    monkeypatch.setattr(storage, "stage", stage)
    storage.register(head)
    monkeypatch.setattr(mutations, "get_storage", lambda: storage)
    store = DatabaseThreads(database)
    monkeypatch.setattr(threads, "get_store", lambda: store)
    monkeypatch.setattr(service.settings, "ai_mutations_enabled", True)
    monkeypatch.setattr(service.settings, "ai_store", "supabase")
    monkeypatch.setattr(service.settings, "hf_read_only", False)
    monkeypatch.setattr(service.settings, "auth_required", True)
    monkeypatch.setattr(auth, "verify_jwt", lambda token, **kwargs: {"sub": token})
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(router)
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + head.owner
    token = current_owner.set(head.owner)
    try:
        yield SimpleNamespace(
            storage=storage,
            head=head,
            suggestion=suggestion,
            store=store,
            client=client,
            objects=objects,
        )
    finally:
        current_owner.reset(token)


def apply(s):
    return s.client.post(f"/ai/suggestions/{s.suggestion.id}/apply", json={})


def test_http_apply_retry_history_undo_and_current_validation(setup):
    s = setup
    response = apply(s)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["changes"]) == 2
    assert {c["operation_id"] for c in body["changes"]} == {body["operation_id"]}
    assert apply(s).json() == body
    assert s.client.post(f"/ai/suggestions/{s.suggestion.id}/reject").status_code == 409
    assert (
        s.store.get(s.head.owner, s.suggestion.id.split(":")[0])
        .data.suggestions[0]
        .suggestion.status
        == SuggestionStatus.applied
    )
    assert (
        s.client.post(
            "/ai/validate", json={"scope": s.suggestion.scope.model_dump(mode="json")}
        ).status_code
        == 409
    )
    scope = s.suggestion.scope.model_copy(update={"version": body["change"]["version"]})
    assert (
        s.client.post("/ai/validate", json={"scope": scope.model_dump(mode="json")}).status_code
        == 200
    )
    page = s.client.get("/ai/changes", params={"corpus": "mini", "limit": 1}).json()
    assert page["next_offset"] == 1
    second = s.client.get("/ai/changes", params={"corpus": "mini", "limit": 1, "offset": 1}).json()
    assert second["next_offset"] is None
    assert page["entries"][0]["change_id"] != second["entries"][0]["change_id"]
    selected = body["changes"][1]["change_id"]
    undone = s.client.post(f"/ai/changes/{selected}/undo")
    assert undone.status_code == 200, undone.text
    inverse = undone.json()
    assert inverse["revert"]["reverts"] == selected
    assert {e["reverts"] for e in inverse["reverts"]} == {e["change_id"] for e in body["changes"]}
    assert s.client.post(f"/ai/changes/{selected}/undo").json() == inverse
    assert len(s.client.get("/ai/changes", params={"corpus": "mini"}).json()["entries"]) == 4
    assert SupabaseJournal(s.storage).pending(s.head.owner) == []


def test_rejection_during_staging_prevents_publication(setup, monkeypatch):
    s = setup
    stage = s.storage.stage

    def reject(*args):
        result = stage(*args)
        threads.transition_suggestion(s.suggestion.id, SuggestionStatus.rejected)
        return result

    monkeypatch.setattr(s.storage, "stage", reject)
    assert apply(s).status_code == 409
    assert s.storage.resolve(s.head.owner, "mini") == s.head
    assert len(SupabaseJournal(s.storage).pending(s.head.owner)) == 1
    assert s.client.get("/ai/changes", params={"corpus": "mini"}).json()["entries"] == []
    assert apply(s).status_code == 409


def test_publication_between_rejection_read_and_cas_wins(setup, monkeypatch):
    s = setup
    replace = s.store.replace
    fired = False

    def race(record):
        nonlocal fired
        if not fired:
            fired = True
            assert mutations.apply(s.suggestion.id).status == SuggestionStatus.applied
        return replace(record)

    monkeypatch.setattr(s.store, "replace", race)
    result = s.client.post(f"/ai/suggestions/{s.suggestion.id}/reject")
    assert result.status_code == 409
    assert s.storage.resolve(s.head.owner, "mini").version == "v1.1"


def test_owner_lock_and_unprovisioned_boundaries(setup):
    s = setup
    assert apply(s).status_code == 200
    change_id = s.client.get("/ai/changes", params={"corpus": "mini"}).json()["entries"][0][
        "change_id"
    ]
    foreign = {"Authorization": "Bearer " + str(uuid4())}
    assert (
        s.client.post(
            f"/ai/suggestions/{s.suggestion.id}/apply", json={}, headers=foreign
        ).status_code
        == 404
    )
    assert s.client.post(f"/ai/changes/{change_id}/undo", headers=foreign).status_code == 404
    assert (
        s.client.get("/ai/changes", params={"corpus": "mini"}, headers=foreign).status_code == 404
    )
    assert s.client.get("/ai/changes", params={"corpus": "unregistered"}).status_code == 404
    s.storage.set_state(s.head.owner, "mini", "published")
    assert s.client.post(f"/ai/changes/{change_id}/undo").status_code == 423
    assert s.client.get("/ai/changes", params={"corpus": "mini"}).status_code == 200


def test_registry_outage_never_falls_back_to_original(setup, monkeypatch):
    def unavailable(*args):
        raise JournalUnavailableError("secret backend")

    monkeypatch.setattr(setup.storage, "resolve", unavailable)

    def legacy(*args, **kwargs):
        pytest.fail("must not fall back on registry outage")

    monkeypatch.setattr(service.storage.corpus_storage, "download", legacy)
    assert apply(setup).status_code == 503
    response = setup.client.post(
        "/ai/validate", json={"scope": setup.suggestion.scope.model_dump(mode="json")}
    )
    assert response.status_code == 503
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_mcp_apply_history_and_undo_share_service(setup):
    mcp = FastMCP("mutations")
    register_curation_tools(mcp)
    async with Client(mcp) as client:
        result = await client.call_tool("apply_node_fix", {"suggestion_id": setup.suggestion.id})
        body = result.data
        assert len(body["changes"]) == 2
        history = await client.call_tool("get_change_log", {"corpus": "mini"})
        assert len(history.data["entries"]) == 2
        undone = await client.call_tool("undo_change", {"change_id": body["change"]["change_id"]})
        assert len(undone.data["reverts"]) == 2
        invalid = await client.call_tool(
            "get_change_log", {"corpus": "mini", "limit": 1000}, raise_on_error=False
        )
        assert invalid.is_error


def test_disabled_and_anonymous_fail_closed(monkeypatch):
    monkeypatch.setattr(service.settings, "ai_mutations_enabled", False)
    with pytest.raises(service.CurationError) as error:
        mutations.apply("anything")
    assert error.value.status == 501
    monkeypatch.setattr(service.settings, "ai_mutations_enabled", True)
    token = current_owner.set(None)
    try:
        with pytest.raises(service.CurationError) as error:
            mutations.history("mini")
        assert error.value.status == 403
    finally:
        current_owner.reset(token)


def test_stored_payload_change_during_staging_blocks_publication(setup, monkeypatch):
    s = setup
    stage = s.storage.stage

    def change(*args):
        key = stage(*args)
        record = s.store.get(s.head.owner, s.suggestion.id.split(":")[0])
        record.data.suggestions[0].suggestion.diff[0].new = "99"
        assert s.store.replace(record)
        return key

    monkeypatch.setattr(s.storage, "stage", change)
    result = apply(s)
    assert result.status_code == 409
    assert result.json()["code"] == "stale"
    assert s.storage.resolve(s.head.owner, "mini") == s.head


def test_history_failure_rolls_back_head_and_suggestion(setup, database, monkeypatch):
    s = setup
    publish = s.storage.publish

    def break_entry(intent):
        # Corrupt one pending field to force finish's row-count invariant.
        # Publication must roll back the pointer AND thread status with history.
        database(
            f"UPDATE public.corpus_changes SET status='failed' WHERE ai_operation_id='{intent.id}' AND field='book';"
        )
        return publish(intent)

    monkeypatch.setattr(s.storage, "publish", break_entry)
    assert apply(s).status_code == 409
    assert s.storage.resolve(s.head.owner, "mini") == s.head
    assert (
        s.store.get(s.head.owner, s.suggestion.id.split(":")[0])
        .data.suggestions[0]
        .suggestion.status
        == SuggestionStatus.pending
    )
    pending = SupabaseJournal(s.storage).pending(s.head.owner)
    assert s.storage.receipt(s.head.owner, pending[0].intent.id) is None


def test_corpus_confirmation_is_not_any_nonempty_token(setup):
    s = setup
    record = s.store.get(s.head.owner, s.suggestion.id.split(":")[0])
    record.data.suggestions[0].suggestion.scope.level = ScopeLevel.corpus
    record.data.suggestions[0].suggestion.scope.node_id = None
    assert s.store.replace(record)
    result = s.client.post(
        f"/ai/suggestions/{s.suggestion.id}/apply", json={"confirmation_token": "yes"}
    )
    assert result.status_code == 428
    assert result.json()["code"] == "confirmation_required"
    assert SupabaseJournal(s.storage).pending(s.head.owner) == []


def test_intervening_edit_blocks_undo(setup):
    s = setup
    first = apply(s).json()
    record = s.store.get(s.head.owner, s.suggestion.id.split(":")[0])
    suggestion = record.data.suggestions[0].suggestion.model_copy(deep=True)
    suggestion.id = record.id + ":" + str(uuid4())
    suggestion.status = SuggestionStatus.pending
    suggestion.base_version = first["change"]["version"]
    suggestion.scope.version = suggestion.base_version
    suggestion.diff = [DiffRow(field="chapter", old="3", new="4")]
    section = ThreadSection(id=str(uuid4()), scope=suggestion.scope, created_at=datetime.now(UTC))
    record.data.thread.sections.append(section)
    record.data.suggestions.append(
        ThreadSuggestion(section_id=section.id, suggestion=suggestion, created_at=datetime.now(UTC))
    )
    assert s.store.replace(record)
    second = s.client.post(f"/ai/suggestions/{suggestion.id}/apply", json={})
    assert second.status_code == 200, second.text
    current = s.storage.resolve(s.head.owner, "mini")
    result = s.client.post(f"/ai/changes/{first['change']['change_id']}/undo")
    assert result.status_code == 409
    assert s.storage.resolve(s.head.owner, "mini") == current


def test_missing_guard_migration_cannot_enable_writes(setup, monkeypatch):
    rpc = setup.storage.rpc

    def old_database(action, owner, payload):
        if action == "capabilities":
            raise service.CurationError(422, "Invalid change storage request")
        return rpc(action, owner, payload)

    monkeypatch.setattr(setup.storage, "rpc", old_database)
    result = apply(setup)
    assert result.status_code == 503
    assert result.json()["retryable"] is True
    assert setup.storage.resolve(setup.head.owner, "mini") == setup.head
    assert SupabaseJournal(setup.storage).pending(setup.head.owner) == []
