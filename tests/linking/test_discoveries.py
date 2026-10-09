import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from corpora_linking import CatalogEntry, SnapshotCatalog, identify_scholarly_citation
from test_scholarly import fixture as scholarly_fixture

from corpora_py.linking_discoveries import SQLiteDiscoveryStore
from corpora_py.linking_store import SQLiteReferenceStore, VersionConflictError


def fixture(tmp_path, works=()):
    snapshot, mention, provenance = scholarly_fixture()
    catalog = SnapshotCatalog(
        entries=tuple(CatalogEntry(work_id=work, names=(mention.cited_name,)) for work in works)
    )
    discovery = identify_scholarly_citation(snapshot, mention, catalog, provenance=provenance)
    store = SQLiteReferenceStore(tmp_path / "working.db", actor_id="creator")
    return store, SQLiteDiscoveryStore(store, authority_id="fixture"), snapshot, discovery


def test_unknown_retry_is_durable_and_does_not_reset_rejection(tmp_path):
    store, discoveries, snapshot, discovery = fixture(tmp_path)
    event_id = uuid4()
    first = discoveries.register(discovery, snapshot, event_id=event_id, reason="recognized")
    assert first.discovery.hypotheses == ()
    reviewer = SQLiteDiscoveryStore(
        SQLiteReferenceStore(store.path, actor_id="reviewer"), authority_id="fixture"
    )
    reviewer.reject(discovery.id, expected_version=1, reason="needs bibliography")
    fresh = identify_scholarly_citation(
        snapshot, discovery.mention, SnapshotCatalog(), provenance=discovery.provenance
    )
    assert fresh.id != discovery.id
    retry = reviewer.register(fresh, snapshot, event_id=event_id, reason="retry")
    assert retry == first
    history = reviewer.history(discovery.id)
    assert [revision.action for revision in history] == ["register", "reject"]
    assert history[-1].actor_id == "reviewer"
    assert reviewer.get(discovery.id) == discovery


def test_explicit_refresh_selects_work_atomically_without_approval(tmp_path):
    store, discoveries, snapshot, discovery = fixture(tmp_path)
    discoveries.register(discovery, snapshot, event_id=uuid4(), reason="recognized")
    catalog = SnapshotCatalog(
        entries=(
            CatalogEntry(work_id="book", names=(discovery.mention.cited_name,)),
            CatalogEntry(work_id="other", names=(discovery.mention.cited_name,)),
        )
    )
    identified = discoveries.refresh_identification(
        discovery.id, snapshot, catalog, expected_version=1, reason="new bibliography"
    )
    assert identified.discovery.id == discovery.id
    assert identified.discovery.work_identification.status == "ambiguous"
    reference = identified.discovery.hypotheses[0]
    selected = discoveries.select_work(
        discovery.id, reference.target.work_id, expected_version=2, reason="reviewer chose work"
    )
    assert selected.selected_reference_id == reference.id
    assert store.get(reference.id) == reference
    assert store.get(reference.id).review == "pending"
    assert store.get(reference.id).resolution == "unresolved"
    assert store.history(reference.id)[0].reason == "reviewer chose work"
    assert len(selected.discovery.hypotheses) == 2
    assert store.get(identified.discovery.hypotheses[1].id) is None
    with pytest.raises(ValueError, match="selected discovery"):
        discoveries.reject(discovery.id, expected_version=3, reason="edit elsewhere")


def test_refresh_preserves_hypothesis_ids_across_disappearance(tmp_path):
    _, discoveries, snapshot, discovery = fixture(tmp_path, works=("book",))
    discoveries.register(discovery, snapshot, event_id=uuid4(), reason="recognized")
    reference_id = discovery.hypotheses[0].id
    discoveries.refresh_identification(
        discovery.id, snapshot, SnapshotCatalog(), expected_version=1, reason="offline"
    )
    catalog = SnapshotCatalog(
        entries=(CatalogEntry(work_id="book", names=(discovery.mention.cited_name,)),)
    )
    restored = discoveries.refresh_identification(
        discovery.id, snapshot, catalog, expected_version=2, reason="restored"
    )
    assert restored.discovery.hypotheses[0].id == reference_id


def test_changed_events_stale_sources_and_invalid_choices_do_not_write(tmp_path):
    _, discoveries, snapshot, discovery = fixture(tmp_path)
    event_id = uuid4()
    discoveries.register(discovery, snapshot, event_id=event_id, reason="recognized")
    changed = discovery.model_copy(
        update={"mention": discovery.mention.model_copy(update={"cited_name": "other"})}
    )
    with pytest.raises(VersionConflictError):
        discoveries.register(changed, snapshot, event_id=event_id, reason="changed")
    with pytest.raises(ValueError, match="stale"):
        discoveries.register(
            discovery,
            snapshot.model_copy(update={"text": snapshot.text.replace("Smith", "Jones")}),
            event_id=uuid4(),
            reason="stale",
        )
    with pytest.raises(ValueError, match="identified work"):
        discoveries.select_work(discovery.id, "invented", expected_version=1, reason="guess")
    with pytest.raises(VersionConflictError):
        discoveries.reject(discovery.id, expected_version=2, reason="stale version")
    assert len(discoveries.history(discovery.id)) == 1


def test_concurrent_retries_reuse_original_ids(tmp_path):
    _, discoveries, snapshot, discovery = fixture(tmp_path, works=("book",))
    event_id = uuid4()

    def register(_):
        return discoveries.register(discovery, snapshot, event_id=event_id, reason="recognized")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, range(2)))
    assert results[0] == results[1]
    assert len(discoveries.history(discovery.id)) == 1


def test_selection_failure_rolls_back_reference_creation(tmp_path):
    store, discoveries, snapshot, discovery = fixture(tmp_path, works=("book",))
    discoveries.register(discovery, snapshot, event_id=uuid4(), reason="recognized")
    with sqlite3.connect(store.path) as db:
        db.execute(
            "CREATE TRIGGER fail_selection BEFORE INSERT ON linking_discovery_revisions WHEN NEW.version = 2 BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        discoveries.select_work(discovery.id, "book", expected_version=1, reason="select")
    assert store.get(discovery.hypotheses[0].id) is None
    assert len(discoveries.history(discovery.id)) == 1


def test_mapping_evidence_survives_refresh_and_selection(tmp_path):
    from corpora_linking import ConversionMapping, Endpoint, PdfLocator, PdfRectangle

    store, discoveries, snapshot, discovery = fixture(tmp_path, works=("book",))
    original = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="pdf",
        revision="pdf:1",
        document_id="asset",
        locators=(
            PdfLocator(asset_id="pdf", page=1, rectangles=(PdfRectangle(x0=1, y0=1, x1=2, y1=2),)),
        ),
    )
    mapping = ConversionMapping(
        original=original, converted=discovery.source, method="fixture", fidelity="approximate"
    )
    event_id = uuid4()
    first = discoveries.register(
        discovery, snapshot, event_id=event_id, reason="recognized", mappings=(mapping,)
    )
    assert first.mappings == (mapping,)
    with pytest.raises(VersionConflictError):
        discoveries.register(discovery, snapshot, event_id=event_id, reason="changed mappings")
    catalog = SnapshotCatalog(
        entries=(CatalogEntry(work_id="book", names=(discovery.mention.cited_name,)),)
    )
    refreshed = discoveries.refresh_identification(
        discovery.id, snapshot, catalog, expected_version=1, reason="fresh catalog"
    )
    selected = discoveries.select_work(discovery.id, "book", expected_version=2, reason="select")
    assert refreshed.mappings == selected.mappings == (mapping,)
    assert store.get(selected.selected_reference_id).review == "pending"
    assert store.history(selected.selected_reference_id)[0].conversion.mappings == (mapping,)


def test_concurrent_work_selection_creates_only_one_reference(tmp_path):
    store, discoveries, snapshot, discovery = fixture(tmp_path, works=("book", "other"))
    discoveries.register(discovery, snapshot, event_id=uuid4(), reason="recognized")

    def select(work):
        try:
            return discoveries.select_work(
                discovery.id, work, expected_version=1, reason="review"
            ).selected_reference_id
        except VersionConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        choices = list(pool.map(select, ["book", "other"]))
    assert sum(choice is not None for choice in choices) == 1
    assert sum(store.get(ref.id) is not None for ref in discovery.hypotheses) == 1
    assert len(discoveries.history(discovery.id)) == 2


def test_discovery_review_example(tmp_path):
    import runpy
    from pathlib import Path

    result = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "packages/linking/examples/discovery_review.py")
    )["discovery_review"]()
    assert [item["action"] for item in result["history"]] == ["register", "identify", "select"]
    assert result["reference"]["review"] == "pending"
    assert result["retry_preserved_ids"]
