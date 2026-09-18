"""Hosted storage regressions; optional real PostgreSQL via an isolated container.

CORPORA_AI_TEST_POSTGRES names a disposable local postgres:17 container whose
anon/authenticated/service_role roles already exist. Each database is temporary.
"""

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
import requests

from corpora_py.ai.schemas import NodeScope, Suggestion
from corpora_py.ai.service import CurationError
from corpora_py.ai.wal import Evidence, Intent, Plan
from corpora_py.ai.wal_sqlite import JournalUnavailableError
from corpora_py.ai.wal_supabase import DraftHead, HostedStorage, SupabaseJournal


@pytest.fixture
def intent():
    owner = str(uuid4())
    before = Evidence(
        revision=str(uuid4()),
        digest="sha256:before",
        version="v1",
        content_hash="h",
        values={"case": "NOM", "lemma": "a"},
    )
    after = Evidence(
        revision=str(uuid4()),
        digest="sha256:after",
        version="v2",
        content_hash="h",
        values={"case": "ACC", "lemma": "b"},
    )
    suggestion = Suggestion(
        id=str(uuid4()) + ":" + str(uuid4()),
        scope=NodeScope(
            corpus="owned", level="word", node_id=1, label="word", version="v1", content_hash="h"
        ),
        kind="annotation",
        target_node=1,
        diff=[
            {"field": "case", "old": "NOM", "new": "ACC"},
            {"field": "lemma", "old": "a", "new": "b"},
        ],
        rationale="reason",
        base_version="v1",
        content_hash="h",
    )
    return Intent(
        id=str(uuid4()),
        owner=owner,
        suggestion=suggestion,
        plan=Plan(before=before, after=after),
        created_at=datetime.now(UTC),
    )


def head_for(intent):
    document = str(uuid4())
    before = intent.plan.before
    return DraftHead(
        document_id=document,
        owner=intent.owner,
        corpus=intent.suggestion.scope.corpus,
        bucket="corpus-ai-drafts",
        object_key=f"{intent.owner}/ai/{document}/{before.revision}.corpus",
        revision=before.revision,
        digest=before.digest,
        version=before.version,
    )


@pytest.mark.parametrize(
    "message,status",
    [("AI_NOT_FOUND", 404), ("AI_LOCKED", 423), ("AI_CONFLICT", 409), ("AI_INVALID", 422)],
)
def test_rpc_maps_only_known_errors(intent, message, status):
    session = Mock()
    session.post.return_value.status_code = 400
    session.post.return_value.json.return_value = {"message": message}
    with pytest.raises(CurationError) as error:
        HostedStorage("https://example.invalid", "secret", session).rpc(
            "get", intent.owner, {"id": intent.id}
        )
    assert error.value.status == status
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("failure", ["body", "network", "json", "missing_config"])
def test_unavailable_errors_never_leak_or_fallback(intent, failure):
    session = Mock()
    session.post.return_value.status_code = 500
    session.post.return_value.json.return_value = {"message": "SQL with secret"}
    if failure == "network":
        session.post.side_effect = requests.ConnectionError("secret URL")
    elif failure == "json":
        session.post.return_value.json.side_effect = ValueError("secret JSON")
    storage = HostedStorage(
        None if failure == "missing_config" else "https://example.invalid", "secret", session
    )
    with pytest.raises(JournalUnavailableError) as error:
        storage.rpc("get", intent.owner, {"id": intent.id})
    assert "secret" not in str(error.value)


def test_stage_never_upserts_and_verifies_readback(intent, tmp_path):
    session = Mock()
    session.post.return_value.status_code = 409
    session.get.return_value = MagicMock()
    response = session.get.return_value.__enter__.return_value
    response.status_code = 200
    response.iter_content.return_value = [b"archive"]
    storage = HostedStorage("https://example.invalid", "secret", session)
    path = tmp_path / "archive.corpus"
    path.write_bytes(b"archive")
    digest = "sha256:" + hashlib.sha256(b"archive").hexdigest()
    head = head_for(intent)
    key = storage.stage(head, intent.plan.after.revision, path, digest)
    assert key == head.key_for(intent.plan.after.revision)
    assert session.post.call_args.kwargs["headers"]["x-upsert"] == "false"
    response.iter_content.return_value = [b"other"]
    with pytest.raises(CurationError) as error:
        storage.stage(head, intent.plan.after.revision, path, digest)
    assert error.value.status == 409


def test_wrong_bytes_and_foreign_path_are_rejected_before_upload(intent, tmp_path):
    session = Mock()
    storage = HostedStorage("https://example.invalid", "secret", session)
    path = tmp_path / "archive"
    path.write_bytes(b"wrong")
    with pytest.raises(CurationError):
        storage.stage(head_for(intent), intent.plan.after.revision, path, "sha256:expected")
    assert not session.post.called
    with pytest.raises(CurationError):
        storage.verify_object(head_for(intent), "someone-else/secret.corpus", "hash")
    assert not session.get.called


def test_journal_rpc_uses_atomic_group_and_verified_owner(intent):
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {
        "intent": intent.model_dump(mode="json"),
        "applied_at": None,
    }
    journal = SupabaseJournal(HostedStorage("https://example.invalid", "secret", session))
    assert journal.insert(intent).intent == intent
    sent = session.post.call_args.kwargs["json"]
    assert sent["p_owner"] == intent.owner
    assert sent["p_action"] == "insert"
    assert len(sent["p_payload"]["entries"]) == 2
    assert sent["p_payload"]["proof"] == intent.proof
    assert "secret" not in json.dumps(sent)


@pytest.fixture(scope="module")
def postgres():
    container = os.getenv("CORPORA_AI_TEST_POSTGRES")
    if not container:
        pytest.skip("Set CORPORA_AI_TEST_POSTGRES to run isolated PostgreSQL integration tests")
    database = "ai_test_" + uuid4().hex

    def command(args, sql=None, check=True):
        return subprocess.run(
            ["docker", "exec", "-i", container, *args],
            input=sql,
            text=True,
            capture_output=True,
            check=check,
        )

    command(["createdb", "-U", "postgres", database])

    def query(sql, check=True):
        return command(
            ["psql", "-U", "postgres", "-d", database, "-qAt", "-v", "ON_ERROR_STOP=1"], sql, check
        )

    root = Path(__file__).resolve().parents[2]
    try:
        query((root / "packages/admin/sql/tests/ai_hosted_bootstrap.sql").read_text())
        query(
            (
                root / "packages/admin/sql/migrations/20260918154935_ai_hosted_journal.sql"
            ).read_text()
        )
        yield query
    finally:
        command(["dropdb", "-U", "postgres", database])


def literal(value):
    return "'" + value.replace("'", "''") + "'"


class DatabaseSession:
    """Drive the real SQL function using the exact PostgREST request payload."""

    def __init__(self, query):
        self.query = query

    def post(self, url, *, headers, json, timeout):
        assert url.endswith("/rest/v1/rpc/corpora_ai_storage")
        result = self.query(
            "SET ROLE service_role; SELECT public.corpora_ai_storage("
            + ",".join(
                [
                    literal(json["p_action"]),
                    literal(json["p_owner"]) + "::uuid",
                    literal(__import__("json").dumps(json["p_payload"])) + "::jsonb",
                ]
            )
            + ");",
            check=False,
        )
        response = Mock()
        response.status_code = 200 if result.returncode == 0 else 400
        if result.returncode:
            message = next(
                (
                    m
                    for m in ["AI_NOT_FOUND", "AI_LOCKED", "AI_CONFLICT", "AI_INVALID"]
                    if m in result.stderr
                ),
                result.stderr,
            )
            response.json.return_value = {"message": message}
        else:
            response.json.return_value = __import__("json").loads(result.stdout.strip() or "null")
        return response


@pytest.fixture
def hosted(postgres, intent, monkeypatch):
    head = head_for(intent)
    postgres(
        f"INSERT INTO public.users VALUES ('{intent.owner}'); INSERT INTO public.corpus_documents VALUES ('{head.document_id}');"
    )
    storage = HostedStorage("https://local.invalid", "test-key", DatabaseSession(postgres))
    # Actual immutable-object transport is covered above; Postgres owns pointers,
    # transactional field entries and receipts, not object bytes.
    monkeypatch.setattr(storage, "verify_object", lambda *args: None)
    assert storage.register(head) == head
    return storage, SupabaseJournal(storage), head


def test_postgres_multifield_publication_finish_and_retry(hosted, intent, postgres):
    storage, journal, head = hosted
    assert journal.insert(intent).applied_at is None
    assert journal.insert(intent).intent == intent
    assert len(journal.pending(intent.owner)) == 1
    assert storage.resolve(intent.owner, "owned") == head
    with pytest.raises(CurationError):
        journal.finish(intent.owner, intent.id, datetime.now(UTC))
    assert storage.publish(intent)
    receipt = storage.receipt(intent.owner, intent.id)
    applied = journal.finish(intent.owner, intent.id, datetime(2000, 1, 1, tzinfo=UTC))
    assert applied.applied_at == receipt.applied_at
    assert journal.finish(intent.owner, intent.id, datetime.now(UTC)) == applied
    assert storage.publish(intent)
    assert journal.pending(intent.owner) == []
    assert storage.resolve(intent.owner, "owned").revision == intent.plan.after.revision
    rows = json.loads(
        postgres(
            f"SELECT json_agg(json_build_object('field',field,'status',status)) FROM public.corpus_changes WHERE ai_operation_id='{intent.id}';"
        ).stdout
    )
    assert {r["field"] for r in rows} == {"case", "lemma"}
    assert all(r["status"] == "applied" for r in rows)


def test_postgres_rollback_on_one_bad_field(hosted, intent, postgres):
    storage, journal, head = hosted
    entries = [e.model_dump(mode="json") for e in intent.entries(intent.created_at)]
    entries[1]["previous_value"] = "incorrect"
    with pytest.raises(CurationError):
        storage.rpc(
            "insert",
            intent.owner,
            {"intent": intent.model_dump(mode="json"), "proof": intent.proof, "entries": entries},
        )
    assert journal.get(intent.owner, intent.id) is None
    assert (
        postgres(
            f"SELECT count(*) FROM public.corpus_changes WHERE ai_operation_id='{intent.id}';"
        ).stdout.strip()
        == "0"
    )
    assert storage.resolve(intent.owner, "owned") == head


def test_postgres_competing_publications_have_one_winner(hosted, intent):
    storage, journal, head = hosted
    other = intent.model_copy(
        update={
            "id": str(uuid4()),
            "suggestion": intent.suggestion.model_copy(update={"id": "other"}),
            "plan": intent.plan.model_copy(
                update={
                    "after": intent.plan.after.model_copy(
                        update={"revision": str(uuid4()), "digest": "other"}
                    )
                }
            ),
        }
    )
    journal.insert(intent)
    journal.insert(other)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(storage.publish, [intent, other]))
    assert sorted(results) == [False, True]
    assert sum(storage.receipt(i.owner, i.id) is not None for i in [intent, other]) == 1


def test_postgres_lock_foreign_owner_and_private_history(hosted, intent, postgres):
    storage, journal, head = hosted
    journal.insert(intent)
    foreign = str(uuid4())
    assert journal.get(foreign, intent.id) is None
    assert journal.pending(foreign) == []
    with pytest.raises(CurationError):
        storage.resolve(foreign, "owned")
    storage.set_state(intent.owner, "owned", "locked")
    with pytest.raises(CurationError) as error:
        storage.publish(intent)
    assert error.value.status == 423
    assert storage.receipt(intent.owner, intent.id) is None
    for owner, count in [(intent.owner, "2"), (foreign, "0")]:
        result = postgres(
            f"SET ROLE authenticated; SET request.jwt.claim.sub='{owner}'; SELECT count(*) FROM public.corpus_changes WHERE ai_operation_id='{intent.id}';"
        )
        assert result.stdout.strip() == count
    assert (
        postgres(
            "SET ROLE anon; SELECT public.corpora_ai_storage('pending',gen_random_uuid(),'{\"limit\":1}');",
            check=False,
        ).returncode
        != 0
    )
    assert (
        postgres(
            "SET ROLE authenticated; SELECT * FROM public.corpus_ai_operations;", check=False
        ).returncode
        != 0
    )
    assert (
        postgres("SET ROLE authenticated; TRUNCATE public.corpus_changes;", check=False).returncode
        != 0
    )
    assert (
        postgres(
            "SET ROLE authenticated; INSERT INTO storage.objects VALUES (gen_random_uuid(),'corpus-ai-drafts');",
            check=False,
        ).returncode
        != 0
    )


def test_postgres_receipt_survives_later_head_and_locked_finalization(hosted, intent):
    storage, journal, head = hosted
    journal.insert(intent)
    storage.publish(intent)
    receipt = storage.receipt(intent.owner, intent.id)
    after = intent.plan.after.model_copy(
        update={
            "revision": str(uuid4()),
            "version": "v3",
            "digest": "next",
            "values": {"case": "DAT", "lemma": "c"},
        }
    )
    scope = intent.suggestion.scope.model_copy(update={"version": "v2"})
    suggestion = Suggestion.model_validate(
        {
            **intent.suggestion.model_dump(),
            "id": "next",
            "scope": scope,
            "base_version": "v2",
            "diff": [
                {"field": "case", "old": "ACC", "new": "DAT"},
                {"field": "lemma", "old": "b", "new": "c"},
            ],
        }
    )
    next_intent = intent.model_copy(
        update={
            "id": str(uuid4()),
            "suggestion": suggestion,
            "plan": Plan(before=intent.plan.after, after=after),
        }
    )
    journal.insert(next_intent)
    storage.publish(next_intent)
    storage.set_state(intent.owner, "owned", "published")
    assert (
        journal.finish(intent.owner, intent.id, datetime.now(UTC)).applied_at == receipt.applied_at
    )
    assert storage.resolve(intent.owner, "owned").version == "v3"


def test_postgres_engine_apply_and_undo_round_trip(hosted, intent, postgres):
    from corpora_py.ai.wal import MutationEngine

    storage, journal, head = hosted
    states = {intent.plan.before.revision: intent.plan.before}

    class DraftAdapter:
        def authorize(self, owner, corpus):
            if storage.resolve(owner, corpus).state != "draft":
                raise CurationError(423, "Locked")

        def confirm(self, *args):
            raise AssertionError("Word scope does not require confirmation")

        def read(self, operation):
            current = storage.resolve(operation.owner, operation.suggestion.scope.corpus)
            return states[current.revision]

        def prepare(self, owner, suggestion):
            current = storage.resolve(owner, suggestion.scope.corpus)
            before = states[current.revision]
            values = dict(before.values)
            values.update({r.field: r.new for r in suggestion.diff})
            after = before.model_copy(
                update={
                    "revision": str(uuid4()),
                    "digest": str(uuid4()),
                    "version": "v" + str(int(before.version[1:]) + 1),
                    "values": values,
                }
            )
            states[after.revision] = after
            return Plan(before=before, after=after)

        def receipt(self, operation):
            return storage.receipt(operation.owner, operation.id)

        def commit(self, operation):
            return storage.publish(operation)

    engine = MutationEngine(journal, DraftAdapter())
    applied = engine.apply(intent.owner, intent.suggestion)
    assert engine.apply(intent.owner, intent.suggestion) == applied
    undo = engine.undo(intent.owner, applied.intent.id)
    assert engine.undo(intent.owner, applied.intent.id) == undo
    assert (
        states[storage.resolve(intent.owner, "owned").revision].values == intent.plan.before.values
    )
    rows = json.loads(
        postgres(
            f"SELECT json_agg(json_build_object('id',id,'reverts',reverts_change_id,'resp',resp)) FROM public.corpus_changes WHERE ai_operation_id='{undo.intent.id}';"
        ).stdout
    )
    assert {r["reverts"] for r in rows} == {
        e.change_id for e in applied.intent.entries(applied.applied_at)
    }
    assert all(r["resp"] == ["#corpora-ai", "#" + intent.owner] for r in rows)


def test_postgres_legacy_visibility_and_delete_protection(hosted, intent, postgres):
    storage, journal, head = hosted
    journal.insert(intent)
    legacy = str(uuid4())
    postgres(
        f"INSERT INTO public.corpus_changes(id,document_id,version,node_id,field,previous_value,new_value,kind,resp,applied_by) VALUES ('{legacy}','{head.document_id}','v1',1,'legacy','a','b','annotation',ARRAY['#legacy','#user'],'{intent.owner}');"
    )
    assert (
        postgres(
            f"SET ROLE authenticated; SELECT count(*) FROM public.corpus_changes WHERE id='{legacy}';"
        ).stdout.strip()
        == "1"
    )
    assert (
        postgres(
            f"DELETE FROM public.corpus_documents WHERE id='{head.document_id}';", check=False
        ).returncode
        != 0
    )
    bad = head.model_copy(update={"owner": str(uuid4())})
    postgres(f"INSERT INTO public.users VALUES ('{bad.owner}');")
    with pytest.raises((CurationError, JournalUnavailableError)):
        storage.register(bad)
    assert storage.resolve(intent.owner, "owned") == head


def test_postgres_migration_security_settings(postgres):
    result = json.loads(
        postgres("""SELECT json_build_object(
        'rls', (SELECT bool_and(relrowsecurity) FROM pg_class WHERE oid IN ('public.corpus_ai_drafts'::regclass,'public.corpus_ai_operations'::regclass)),
        'invoker', (SELECT NOT prosecdef FROM pg_proc WHERE oid='public.corpora_ai_storage(text,uuid,jsonb)'::regprocedure),
        'anon_rpc', has_function_privilege('anon','public.corpora_ai_storage(text,uuid,jsonb)','EXECUTE'),
        'auth_rpc', has_function_privilege('authenticated','public.corpora_ai_storage(text,uuid,jsonb)','EXECUTE'),
        'service_rpc', has_function_privilege('service_role','public.corpora_ai_storage(text,uuid,jsonb)','EXECUTE'),
        'anon_table', has_table_privilege('anon','public.corpus_ai_operations','SELECT'),
        'auth_table', has_table_privilege('authenticated','public.corpus_ai_drafts','UPDATE'),
        'private_bucket', (SELECT NOT public FROM storage.buckets WHERE id='corpus-ai-drafts'));
    """).stdout
    )
    assert result == {
        "rls": True,
        "invoker": True,
        "anon_rpc": False,
        "auth_rpc": False,
        "service_rpc": True,
        "anon_table": False,
        "auth_table": False,
        "private_bucket": True,
    }


def test_postgres_cannot_reuse_historical_revision(hosted, intent):
    storage, journal, head = hosted
    journal.insert(intent)
    storage.publish(intent)
    suggestion = Suggestion.model_validate(
        {
            **intent.suggestion.model_dump(),
            "id": "second",
            "scope": intent.suggestion.scope.model_copy(update={"version": "v2"}),
            "base_version": "v2",
            "diff": [
                {"field": "case", "old": "ACC", "new": "NOM"},
                {"field": "lemma", "old": "b", "new": "a"},
            ],
        }
    )
    after = intent.plan.before.model_copy(update={"version": "v3"})
    reused = intent.model_copy(
        update={
            "id": str(uuid4()),
            "suggestion": suggestion,
            "plan": Plan(before=intent.plan.after, after=after),
        }
    )
    with pytest.raises(CurationError) as error:
        journal.insert(reused)
    assert error.value.status == 409
    assert journal.get(intent.owner, reused.id) is None
