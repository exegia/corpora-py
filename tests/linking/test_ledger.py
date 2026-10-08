import runpy
from pathlib import Path
from uuid import uuid4

import pytest
from corpora_linking import (
    CatalogEntry,
    Endpoint,
    Reference,
    SnapshotCatalog,
    SnapshotResolver,
    TextSnapshot,
)

from corpora_py.linking_ledger import PublicationLedger
from corpora_py.linking_publication import SnapshotPublicationAdapter
from corpora_py.linking_store import SQLiteReferenceStore, VersionConflictError


def fixture(tmp_path):
    example = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "packages/linking/examples/review_link.py")
    )
    history = example["review_link"]()
    store = SQLiteReferenceStore(tmp_path / "working.db", actor_id="operator")
    pending = history[0].reference
    base = Endpoint.model_validate({**pending.source.model_dump(), "locators": []})
    resolver = SnapshotResolver(
        catalog=SnapshotCatalog(
            entries=(
                CatalogEntry(work_id=pending.source.work_id, names=("Source",)),
                CatalogEntry(work_id=pending.target.work_id, names=("Target",)),
            )
        ),
        snapshots=(
            TextSnapshot(
                endpoint=base,
                stream_id=pending.source.locators[0].stream_id,
                text=pending.source.locators[0].exact,
            ),
        ),
    )
    store.save(pending, expected_version=None)
    store.approve(pending.id, expected_version=1, resolver=resolver, reason="verified fixture")
    adapter = SnapshotPublicationAdapter("fixture:local")
    ref = store.get(pending.id)
    payload = adapter.export_working(store, (ref.id,))
    return store, ref, payload, PublicationLedger(store, authority_id="fixture:local")


def test_acknowledgment_and_withdrawal_are_atomic_audited_and_replayable(tmp_path):
    store, ref, payload, ledger = fixture(tmp_path)
    event_id = uuid4()
    event = ledger.acknowledge_snapshot(
        payload,
        ref.id,
        event_id=event_id,
        expected_version=2,
        reason="local fixture acknowledgment",
    )
    assert event.working_version == 3 and event.snapshot_version == 2
    assert store.get(ref.id).publication == "published"
    assert (
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=event_id, expected_version=2, reason=event.reason
        )
        == event
    )
    assert len(store.history(ref.id)) == 3
    withdrawal_id = uuid4()
    withdrawn = ledger.withdraw(
        ref.id, event_id=withdrawal_id, expected_version=3, reason="withdraw fixture"
    )
    assert withdrawn.artifact_digest == event.artifact_digest and withdrawn.working_version == 4
    assert store.get(ref.id).publication == "withdrawn" and store.get(ref.id).review == "approved"
    assert ledger.pending_removals() == (withdrawn,)
    assert (
        ledger.withdraw(ref.id, event_id=withdrawal_id, expected_version=3, reason=withdrawn.reason)
        == withdrawn
    )
    assert len(store.history(ref.id)) == 4
    # Replaying an old acknowledgment does not restore withdrawn publication.
    assert (
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=event_id, expected_version=2, reason=event.reason
        )
        == event
    )
    assert store.get(ref.id).publication == "withdrawn"


def test_stale_export_and_changed_artifact_do_not_acknowledge(tmp_path):
    store, ref, payload, ledger = fixture(tmp_path)
    store.save(
        Reference.model_validate({**ref.model_dump(), "review": "pending"}), expected_version=2
    )
    with pytest.raises(VersionConflictError):
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=uuid4(), expected_version=2, reason="stale"
        )
    with pytest.raises(ValueError, match="current audited"):
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=uuid4(), expected_version=3, reason="stale version"
        )
    assert ledger.history(ref.id) == ()


def test_event_identity_collision_and_wrong_authority_reject(tmp_path):
    store, ref, payload, ledger = fixture(tmp_path)
    event_id = uuid4()
    ledger.acknowledge_snapshot(
        payload, ref.id, event_id=event_id, expected_version=2, reason="fixture"
    )
    with pytest.raises(ValueError, match="another acknowledgment"):
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=event_id, expected_version=2, reason="different"
        )
    wrong = PublicationLedger(store, authority_id="foreign")
    with pytest.raises(ValueError, match="authority"):
        wrong.acknowledge_snapshot(
            payload, ref.id, event_id=uuid4(), expected_version=3, reason="wrong authority"
        )


def test_published_edit_requires_withdrawal_and_reopening(tmp_path):
    store, ref, payload, ledger = fixture(tmp_path)
    ledger.acknowledge_snapshot(
        payload, ref.id, event_id=uuid4(), expected_version=2, reason="fixture"
    )
    pending = Reference.model_validate({**ref.model_dump(), "review": "pending"})
    with pytest.raises(ValueError):
        store.save(pending, expected_version=3)
    with pytest.raises(ValueError, match="withdrawn"):
        store.reopen(ref.id, expected_version=3, reason="cannot bypass withdrawal")
    ledger.withdraw(ref.id, event_id=uuid4(), expected_version=3, reason="replace publication")
    assert store.reopen(ref.id, expected_version=4, reason="new review") == 5
    assert store.get(ref.id).publication == "draft" and store.get(ref.id).review == "pending"
    assert len(ledger.pending_removals()) == 1


def test_unpublished_and_duplicate_withdrawal_reject(tmp_path):
    store, ref, payload, ledger = fixture(tmp_path)
    with pytest.raises(ValueError, match="acknowledged published"):
        ledger.withdraw(ref.id, event_id=uuid4(), expected_version=2, reason="not published")
    ledger.acknowledge_snapshot(
        payload, ref.id, event_id=uuid4(), expected_version=2, reason="fixture"
    )
    ledger.withdraw(ref.id, event_id=uuid4(), expected_version=3, reason="withdraw")
    with pytest.raises(ValueError):
        ledger.withdraw(ref.id, event_id=uuid4(), expected_version=4, reason="already withdrawn")


def test_withdrawn_reference_is_omitted_from_next_snapshot(tmp_path):
    from corpora_py.linking_publication import PublicationSnapshot

    store, ref, payload, ledger = fixture(tmp_path)
    ledger.acknowledge_snapshot(
        payload, ref.id, event_id=uuid4(), expected_version=2, reason="fixture"
    )
    assert (
        PublicationSnapshot.model_validate_json(ledger.export_current((ref.id,)))
        .entries[0]
        .reference.id
        == ref.id
    )
    ledger.withdraw(ref.id, event_id=uuid4(), expected_version=3, reason="withdraw")
    assert PublicationSnapshot.model_validate_json(ledger.export_current((ref.id,))).entries == ()
    assert len(store.history(ref.id)) == 4


def test_payload_content_and_versionless_acknowledgments_reject(tmp_path):
    store, ref, payload, ledger = fixture(tmp_path)
    adapter = SnapshotPublicationAdapter("fixture:local")
    with pytest.raises(ValueError, match="versioned snapshot"):
        ledger.acknowledge_snapshot(
            adapter.export((ref,)),
            ref.id,
            event_id=uuid4(),
            expected_version=2,
            reason="no version",
        )
    changed = Reference.model_validate({**ref.model_dump(), "relationship": "core:related"})
    with pytest.raises(ValueError, match="content differs"):
        ledger.acknowledge_snapshot(
            adapter.export((changed,), versions={ref.id: 2}),
            ref.id,
            event_id=uuid4(),
            expected_version=2,
            reason="wrong content",
        )
    assert ledger.history(ref.id) == () and len(store.history(ref.id)) == 2


def test_concurrent_acknowledgments_commit_one_atomic_revision(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store, ref, payload, ledger = fixture(tmp_path)
    barrier = Barrier(2)

    def acknowledge(_):
        barrier.wait(timeout=5)
        try:
            return ledger.acknowledge_snapshot(
                payload, ref.id, event_id=uuid4(), expected_version=2, reason="concurrent fixture"
            ).working_version
        except VersionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(acknowledge, (1, 2))) == {3, "conflict"}
    assert len(ledger.history(ref.id)) == 1 and len(store.history(ref.id)) == 3


def test_failed_event_insert_rolls_back_working_revision(tmp_path):
    import sqlite3

    store, ref, payload, ledger = fixture(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute(
            "CREATE TRIGGER fail_ledger BEFORE INSERT ON linking_publication_events BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="fixture failure"):
        ledger.acknowledge_snapshot(
            payload, ref.id, event_id=uuid4(), expected_version=2, reason="rollback fixture"
        )
    assert len(store.history(ref.id)) == 2 and store.get(ref.id).publication == "draft"
    assert ledger.history(ref.id) == ()
