"""Failure-injection tests for the write-ahead protocol.

The draft fixture uses a real SQLite transaction for CAS + receipt, representing
an adapter contract; it does not claim existing archive uploads are atomic.
"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from corpora_py.ai.schemas import NodeScope, ScopeLevel, Suggestion
from corpora_py.ai.service import CurationError
from corpora_py.ai.wal import Evidence, Intent, MutationEngine, Plan, Receipt
from corpora_py.ai.wal_sqlite import JournalUnavailableError, SQLiteJournal


class CrashError(Exception):
    pass


class DraftFixture:
    def __init__(self, path, journal):
        self.path, self.journal = path, journal
        self.crash = None
        self.locked = False
        self.commits = 0
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS head(data TEXT);
                CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, data TEXT);""")
            if not db.execute("SELECT data FROM head").fetchone():
                evidence = Evidence(
                    revision="r1",
                    digest="d1",
                    version="v1",
                    content_hash="h1",
                    values={"case": "NOM", "lemma": "a"},
                )
                db.execute("INSERT INTO head VALUES(?)", (evidence.model_dump_json(),))
            db.commit()

    def authorize(self, owner, corpus):
        if owner != "alice" or corpus != "draft":
            raise CurationError(404, "Draft not found")
        if self.locked:
            raise CurationError(423, "Published or locked")

    def confirm(self, owner, suggestion, token):
        if token != f"{owner}:{suggestion.id}:{suggestion.base_version}":
            raise CurationError(428, "Bound confirmation required")

    def read(self, intent=None):
        with closing(sqlite3.connect(self.path)) as db:
            return Evidence.model_validate_json(db.execute("SELECT data FROM head").fetchone()[0])

    def prepare(self, owner, suggestion):
        self.authorize(owner, suggestion.scope.corpus)
        if suggestion.target_node != 1 or suggestion.scope.node_id not in (None, 1):
            raise CurationError(422, "Target outside scope")
        before = self.read()
        values = dict(before.values)
        values.update({r.field: r.new for r in suggestion.diff})
        after = Evidence(
            revision=str(uuid4()),
            digest=str(uuid4()),
            version="v" + str(int(before.version[1:]) + 1),
            content_hash=before.content_hash,
            values=values,
        )
        return Plan(before=before, after=after)

    def receipt(self, intent):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT data FROM receipts WHERE id=?", (intent.id,)).fetchone()
        return Receipt.model_validate_json(row[0]) if row else None

    def commit(self, intent):
        self.authorize(intent.owner, intent.suggestion.scope.corpus)
        assert self.journal.get(intent.owner, intent.id) is not None
        if self.crash == "before":
            raise CrashError()
        with closing(sqlite3.connect(self.path, timeout=15)) as db:
            db.execute("BEGIN IMMEDIATE")
            current = Evidence.model_validate_json(
                db.execute("SELECT data FROM head").fetchone()[0]
            )
            if current != intent.plan.before:
                db.rollback()
                return False
            self.commits += 1
            db.execute("UPDATE head SET data=?", (intent.plan.after.model_dump_json(),))
            receipt = Receipt(proof=intent.proof, applied_at=datetime.now(UTC))
            db.execute("INSERT INTO receipts VALUES(?,?)", (intent.id, receipt.model_dump_json()))
            db.commit()
        if self.crash == "after":
            raise CrashError()
        return True

    def replace_head(self, evidence):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE head SET data=?", (evidence.model_dump_json(),))
            db.commit()


@pytest.fixture
def setup(tmp_path):
    journal = SQLiteJournal(tmp_path / "journal.db")
    drafts = DraftFixture(tmp_path / "draft.db", journal)
    engine = MutationEngine(journal, drafts)
    suggestion = Suggestion(
        id="s1",
        scope=NodeScope(
            corpus="draft", level="word", node_id=1, label="word", version="v1", content_hash="h1"
        ),
        kind="annotation",
        target_node=1,
        diff=[
            {"field": "case", "old": "NOM", "new": "ACC"},
            {"field": "lemma", "old": "a", "new": "b"},
        ],
        rationale="reason",
        base_version="v1",
        content_hash="h1",
    )
    return engine, drafts, journal, suggestion


def pending(journal):
    with closing(sqlite3.connect(journal.path)) as db:
        row = db.execute("SELECT intent FROM ai_change_intents WHERE applied_at IS NULL").fetchone()
    return Intent.model_validate_json(row[0])


def test_apply_multifield_retry_and_undo(setup):
    engine, drafts, journal, suggestion = setup
    applied = engine.apply("alice", suggestion)
    assert engine.apply("alice", suggestion) == applied
    assert drafts.commits == 1
    assert drafts.read().values == {"case": "ACC", "lemma": "b"}
    entries = applied.intent.entries(applied.applied_at)
    assert len(entries) == 2 and len({e.change_id for e in entries}) == 2
    assert all(e.resp == ["#corpora-ai", "#alice"] for e in entries)
    undo = engine.undo("alice", applied.intent.id)
    assert drafts.read().values == {"case": "NOM", "lemma": "a"}
    assert drafts.read().version == "v3"
    assert engine.undo("alice", applied.intent.id) == undo
    assert journal.get("alice", applied.intent.id) == applied
    assert [e.reverts for e in undo.intent.entries(undo.applied_at)] == [
        e.change_id for e in entries
    ]


@pytest.mark.parametrize("point", ["before", "after", "finish"])
def test_restart_at_each_crash_point(setup, monkeypatch, point):
    engine, drafts, journal, suggestion = setup
    if point == "finish":
        monkeypatch.setattr(journal, "finish", lambda *args: (_ for _ in ()).throw(CrashError()))
    else:
        drafts.crash = point
    with pytest.raises(CrashError):
        engine.apply("alice", suggestion)
    intent = pending(journal)
    reopened = SQLiteJournal(journal.path)
    fresh = DraftFixture(drafts.path, reopened)
    recovered = MutationEngine(reopened, fresh)
    result = recovered.reconcile("alice", intent.id)
    assert result.state == ("not_applied" if point == "before" else "applied")
    applied = recovered.apply("alice", suggestion)
    assert applied.applied_at is not None
    assert fresh.read().values["case"] == "ACC"
    assert fresh.commits == (1 if point == "before" else 0)
    assert recovered.apply("alice", suggestion) == applied


def test_failed_journal_prevents_publication(setup, monkeypatch):
    engine, drafts, journal, suggestion = setup
    monkeypatch.setattr(
        journal, "insert", lambda *args: (_ for _ in ()).throw(JournalUnavailableError())
    )
    before = drafts.read()
    with pytest.raises(JournalUnavailableError):
        engine.apply("alice", suggestion)
    assert drafts.read() == before
    assert drafts.commits == 0


@pytest.mark.parametrize("replacement", ["after", "partial", "unrelated", "aba"])
def test_recovery_never_infers_success_without_receipt(setup, replacement):
    engine, drafts, journal, suggestion = setup
    drafts.crash = "before"
    with pytest.raises(CrashError):
        engine.apply("alice", suggestion)
    intent = pending(journal)
    if replacement == "after":
        head = intent.plan.after
    elif replacement == "partial":
        head = intent.plan.before.model_copy(update={"values": {"case": "ACC", "lemma": "a"}})
    elif replacement == "aba":
        head = intent.plan.before.model_copy(update={"revision": "another-revision"})
    else:
        head = intent.plan.before.model_copy(update={"digest": "unrelated"})
    drafts.replace_head(head)
    assert engine.reconcile("alice", intent.id).state == "conflict"
    assert journal.get("alice", intent.id).applied_at is None
    with pytest.raises(CurationError) as error:
        engine.apply("alice", suggestion)
    assert error.value.status == 409


def test_receipt_survives_later_edits_and_preserves_publication_time(setup):
    engine, drafts, journal, suggestion = setup
    drafts.crash = "after"
    with pytest.raises(CrashError):
        engine.apply("alice", suggestion)
    intent = pending(journal)
    receipt = drafts.receipt(intent)
    drafts.replace_head(
        intent.plan.after.model_copy(
            update={"revision": "later", "digest": "later", "version": "v9"}
        )
    )
    result = engine.reconcile("alice", intent.id)
    assert result.state == "applied"
    assert result.record.applied_at == receipt.applied_at
    with pytest.raises(CurationError) as error:
        engine.undo("alice", intent.id)
    assert error.value.status == 409


@pytest.mark.parametrize(
    "field,value", [("base_version", "v0"), ("content_hash", "bad"), ("target_node", 2)]
)
def test_stale_or_out_of_scope_rejected_before_intent(setup, field, value):
    engine, drafts, journal, suggestion = setup
    with pytest.raises(CurationError):
        engine.apply("alice", suggestion.model_copy(update={field: value}))
    with closing(sqlite3.connect(journal.path)) as db:
        assert db.execute("SELECT count(*) FROM ai_change_intents").fetchone()[0] == 0
    assert drafts.commits == 0


def test_permissions_locks_and_confirmation(setup):
    engine, drafts, journal, suggestion = setup
    for owner in ["", "bob"]:
        with pytest.raises(CurationError):
            engine.apply(owner, suggestion)
    drafts.locked = True
    with pytest.raises(CurationError) as error:
        engine.apply("alice", suggestion)
    assert error.value.status == 423
    drafts.locked = False
    scope = suggestion.scope.model_copy(update={"level": ScopeLevel.corpus, "node_id": None})
    # Use model validation to preserve enum types.
    wide = Suggestion.model_validate({**suggestion.model_dump(), "scope": scope.model_dump()})
    for token in [None, "yes", "bob:s1:v1", "alice:s1:v0"]:
        with pytest.raises(CurationError) as error:
            engine.apply("alice", wide, token)
        assert error.value.status == 428
    result = engine.apply("alice", wide, "alice:s1:v1")
    assert journal.get("bob", result.intent.id) is None
    with pytest.raises(CurationError):
        engine.undo("bob", result.intent.id)


def test_concurrent_identical_requests_publish_once(setup):
    engine, drafts, journal, suggestion = setup

    def apply(_):
        return engine.apply("alice", suggestion)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, range(2)))
    assert results[0] == results[1]
    assert drafts.commits == 1


def test_changed_retry_payload_rejected(setup):
    engine, drafts, journal, suggestion = setup
    engine.apply("alice", suggestion)
    with pytest.raises(CurationError) as error:
        engine.apply("alice", suggestion.model_copy(update={"rationale": "different"}))
    assert error.value.status == 409


def test_rejected_pending_intent_cannot_resume_publication(setup):
    from corpora_py.ai.schemas import SuggestionStatus

    engine, drafts, journal, suggestion = setup
    drafts.crash = "before"
    with pytest.raises(CrashError):
        engine.apply("alice", suggestion)
    drafts.crash = None
    with pytest.raises(CurationError):
        engine.apply("alice", suggestion.model_copy(update={"status": SuggestionStatus.rejected}))
    assert drafts.commits == 0


def test_undo_rejects_intervening_revision_even_when_values_and_version_match(setup):
    engine, drafts, journal, suggestion = setup
    applied = engine.apply("alice", suggestion)
    drafts.replace_head(drafts.read().model_copy(update={"revision": "intervening"}))
    with pytest.raises(CurationError):
        engine.undo("alice", applied.intent.id)
    assert drafts.read().values["case"] == "ACC"


def test_mismatched_receipt_stays_pending(setup):
    engine, drafts, journal, suggestion = setup
    drafts.crash = "after"
    with pytest.raises(CrashError):
        engine.apply("alice", suggestion)
    intent = pending(journal)
    with closing(sqlite3.connect(drafts.path)) as db:
        wrong = Receipt(proof="another intent", applied_at=datetime.now(UTC))
        db.execute("UPDATE receipts SET data=?", (wrong.model_dump_json(),))
        db.commit()
    assert engine.reconcile("alice", intent.id).state == "conflict"
    assert journal.get("alice", intent.id).applied_at is None


def test_different_writers_on_same_revision_cannot_both_publish(setup, monkeypatch):
    from threading import Barrier

    engine, drafts, journal, suggestion = setup
    barrier = Barrier(2)
    prepare = drafts.prepare

    def together(owner, proposal):
        plan = prepare(owner, proposal)
        barrier.wait(timeout=5)
        return plan

    monkeypatch.setattr(drafts, "prepare", together)

    def apply(proposal):
        try:
            return engine.apply("alice", proposal)
        except CurationError as error:
            assert error.status == 409
            return None

    other = suggestion.model_copy(update={"id": "s2"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, [suggestion, other]))
    assert sum(r is not None for r in results) == 1
    assert drafts.commits == 1
    assert engine.reconcile("alice", pending(journal).id).state == "conflict"


@pytest.mark.parametrize("mutation", ["old_value", "extra_change", "duplicate", "noop"])
def test_complete_diff_is_checked_before_intent(setup, monkeypatch, mutation):
    from corpora_py.ai.schemas import DiffRow

    engine, drafts, journal, suggestion = setup
    if mutation == "old_value":
        suggestion.diff[0] = DiffRow(field="case", old="wrong", new="ACC")
    elif mutation == "duplicate":
        suggestion.diff.append(suggestion.diff[0])
    elif mutation == "noop":
        suggestion.diff[0] = DiffRow(field="case", old="NOM", new="NOM")
    else:
        prepare = drafts.prepare

        def bad_plan(owner, proposal):
            plan = prepare(owner, proposal)
            return Plan(
                before=plan.before,
                after=plan.after.model_copy(
                    update={"values": {"case": "ACC", "lemma": "unrequested"}}
                ),
            )

        monkeypatch.setattr(drafts, "prepare", bad_plan)
    with pytest.raises(CurationError):
        engine.apply("alice", suggestion)
    assert drafts.commits == 0


def test_receipt_proof_ignores_json_object_key_order(setup):
    engine, drafts, journal, suggestion = setup
    applied = engine.apply("alice", suggestion)
    intent = applied.intent.model_dump(mode="json")
    intent["plan"]["before"]["values"] = dict(
        reversed(list(intent["plan"]["before"]["values"].items()))
    )
    assert Intent.model_validate(intent).proof == applied.intent.proof


def test_duplicate_racing_between_lookup_and_prepare_recovers_existing_intent(setup, monkeypatch):
    engine, drafts, journal, suggestion = setup
    prepare = drafts.prepare
    raced = []

    def concurrent_apply(owner, proposal):
        monkeypatch.setattr(drafts, "prepare", prepare)
        raced.append(engine.apply(owner, proposal))
        return prepare(owner, proposal)  # HEAD is now newer than the suggestion.

    monkeypatch.setattr(drafts, "prepare", concurrent_apply)
    result = engine.apply("alice", suggestion)
    assert result == raced[0]
    assert drafts.commits == 1
