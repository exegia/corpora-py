from uuid import uuid4

import pytest
from corpora_linking import BibleBook, BibleCitationDetector, Endpoint, TextSnapshot

from corpora_py.linking_conversion import ConversionInput
from corpora_py.linking_events import ConversionEventRegistry
from corpora_py.linking_store import SQLiteReferenceStore, VersionConflictError


def fixture(tmp_path, text="John 3:16 and John 1:1"):
    base = Endpoint(work_id="essay", edition_id="e", package_id="p", revision="1", document_id="d")
    conversion = ConversionInput(converted=TextSnapshot(endpoint=base, stream_id="body", text=text))
    detector = BibleCitationDetector(
        books=(BibleBook(work_id="john", aliases=("John",)),),
        stream_id="body",
        profile="fixture",
        scheme_id="fixture",
        scheme_version="1",
        agent_id="detector",
    )
    store = SQLiteReferenceStore(tmp_path / "working.db", actor_id="worker")
    return store, ConversionEventRegistry(store, authority_id="fixture"), conversion, detector


def test_retry_returns_original_ids_and_does_not_reset_review(tmp_path):
    store, registry, conversion, detector = fixture(tmp_path)
    event_id = uuid4()
    first = registry.register(
        conversion, detector, event_id=event_id, detector_revision="1", reason="conversion"
    )
    ref = first.report.references[0].reference
    store.reject(ref.id, expected_version=1, reason="reviewed")
    retried = registry.register(
        conversion, detector, event_id=event_id, detector_revision="1", reason="retry"
    )
    assert retried == first and store.get(ref.id).review == "rejected"
    assert len(store.history(ref.id)) == 2
    reopened = ConversionEventRegistry(
        SQLiteReferenceStore(store.path, actor_id="another"), authority_id="fixture"
    )
    assert reopened.get(event_id) == first
    assert len(first.report.references) == 2
    assert store.history(ref.id)[0].conversion == first.report.references[0]


@pytest.mark.parametrize("change", ["text", "revision", "detector", "output"])
def test_changed_event_inputs_require_new_identity(tmp_path, change):
    store, registry, conversion, detector = fixture(tmp_path)
    event_id = uuid4()
    first = registry.register(
        conversion, detector, event_id=event_id, detector_revision="1", reason="conversion"
    )
    revision = "2" if change == "detector" else "1"
    if change == "text":
        conversion = ConversionInput(
            converted=TextSnapshot(
                endpoint=conversion.converted.endpoint, stream_id="body", text="John 3:17"
            )
        )
    if change == "revision":
        endpoint = Endpoint.model_validate(
            {**conversion.converted.endpoint.model_dump(), "revision": "2"}
        )
        conversion = ConversionInput(
            converted=TextSnapshot(
                endpoint=endpoint, stream_id="body", text=conversion.converted.text
            )
        )
    if change == "output":
        detector = BibleCitationDetector.model_validate(
            {**detector.model_dump(), "agent_id": "other-detector"}
        )
    with pytest.raises(VersionConflictError):
        registry.register(
            conversion, detector, event_id=event_id, detector_revision=revision, reason="changed"
        )
    assert registry.get(event_id) == first
    assert all(len(store.history(item.reference.id)) == 1 for item in first.report.references)


def test_distinct_events_do_not_deduplicate_identical_passages(tmp_path):
    _, registry, conversion, detector = fixture(tmp_path)
    one = registry.register(
        conversion, detector, event_id=uuid4(), detector_revision="1", reason="one"
    )
    two = registry.register(
        conversion, detector, event_id=uuid4(), detector_revision="1", reason="two"
    )
    assert {x.reference.id for x in one.report.references}.isdisjoint(
        {x.reference.id for x in two.report.references}
    )
    assert one.input_digest == two.input_digest


def test_empty_detection_is_a_durable_idempotent_event(tmp_path):
    _, registry, conversion, detector = fixture(tmp_path, text="No citation")
    event_id = uuid4()
    first = registry.register(
        conversion, detector, event_id=event_id, detector_revision="1", reason="empty"
    )
    assert not first.report.references
    assert (
        registry.register(
            conversion, detector, event_id=event_id, detector_revision="1", reason="retry"
        )
        == first
    )


def test_concurrent_retries_share_one_committed_set_of_ids(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store, registry, conversion, detector = fixture(tmp_path)
    barrier = Barrier(2)
    event_id = uuid4()

    def register(_):
        barrier.wait(timeout=5)
        return registry.register(
            conversion, detector, event_id=event_id, detector_revision="1", reason="concurrent"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(register, (1, 2))
    assert first == second
    assert all(len(store.history(x.reference.id)) == 1 for x in first.report.references)


def test_event_insert_failure_rolls_back_all_working_references(tmp_path):
    import sqlite3

    store, registry, conversion, detector = fixture(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute(
            "CREATE TRIGGER fail_event BEFORE INSERT ON linking_conversion_events BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    event_id = uuid4()
    with pytest.raises(sqlite3.IntegrityError):
        registry.register(
            conversion, detector, event_id=event_id, detector_revision="1", reason="rollback"
        )
    assert registry.get(event_id) is None
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM linking_revisions").fetchone()[0] == 0


def test_changed_mapping_evidence_conflicts_even_when_text_is_identical(tmp_path):
    from corpora_linking import ConversionMapping, StructuralLocator, TextLocator

    _, registry, conversion, detector = fixture(tmp_path)
    event_id = uuid4()
    registry.register(
        conversion, detector, event_id=event_id, detector_revision="1", reason="original"
    )
    text = conversion.converted.text
    original = Endpoint.model_validate(
        {
            **conversion.converted.endpoint.model_dump(),
            "package_id": "original",
            "locators": [StructuralLocator(anchor_id="source-block")],
        }
    )
    selected = Endpoint.model_validate(
        {
            **conversion.converted.endpoint.model_dump(),
            "locators": [TextLocator(stream_id="body", start=0, end=len(text), exact=text)],
        }
    )
    changed = ConversionInput(
        converted=conversion.converted,
        mappings=(
            ConversionMapping(
                original=original, converted=selected, method="fixture", fidelity="unverified"
            ),
        ),
    )
    with pytest.raises(VersionConflictError):
        registry.register(
            changed, detector, event_id=event_id, detector_revision="1", reason="new evidence"
        )


def test_reference_id_collision_rolls_back_earlier_batch_insert(tmp_path):
    from corpora_linking import Reference

    store, registry, conversion, detector = fixture(tmp_path)
    original = registry.register(
        conversion, detector, event_id=uuid4(), detector_revision="1", reason="original"
    )
    existing = original.report.references[0].reference
    fresh = Reference.model_validate({**existing.model_dump(), "id": uuid4()})

    class CollidingDetector:
        def detect(self, source, text):
            return (fresh, existing)

    event_id = uuid4()
    with pytest.raises(VersionConflictError, match="already belongs"):
        registry.register(
            conversion,
            CollidingDetector(),
            event_id=event_id,
            detector_revision="1",
            reason="collision",
        )
    assert registry.get(event_id) is None and store.get(fresh.id) is None


def test_manual_and_duplicate_detector_records_reject(tmp_path):
    from corpora_linking import Reference

    _, registry, conversion, detector = fixture(tmp_path)
    ref = next(iter(detector.detect(conversion.converted.endpoint, conversion.converted.text)))

    class DuplicateDetector:
        def detect(self, source, text):
            return (ref, ref)

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(
            conversion,
            DuplicateDetector(),
            event_id=uuid4(),
            detector_revision="1",
            reason="bad detector",
        )
    manual = Reference.model_validate(
        {**ref.model_dump(), "provenance": {**ref.provenance.model_dump(), "origin": "manual"}}
    )

    class ManualDetector:
        def detect(self, source, text):
            return (manual,)

    with pytest.raises(ValueError, match="automatic unresolved"):
        registry.register(
            conversion,
            ManualDetector(),
            event_id=uuid4(),
            detector_revision="1",
            reason="bad detector",
        )
