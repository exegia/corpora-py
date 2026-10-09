import runpy
from pathlib import Path

import pytest
from corpora_linking import (
    CatalogEntry,
    Endpoint,
    Provenance,
    Reference,
    SnapshotCatalog,
    SnapshotResolver,
    TextLocator,
    TextSnapshot,
)

from corpora_py.linking_store import SQLiteReferenceStore, VersionConflictError


def fixture(tmp_path, origin="manual"):
    base = Endpoint(work_id="essay", edition_id="e", package_id="p", revision="1", document_id="d")
    selected = Endpoint.model_validate(
        {
            **base.model_dump(),
            "locators": [
                TextLocator(stream_id="body", start=0, end=5, exact="Quote", suffix=" tail")
            ],
        }
    )
    ref = Reference(
        source=selected,
        target=Endpoint(work_id="book"),
        provenance=Provenance(origin=origin, agent_id="creator", method="fixture"),
    )
    resolver = SnapshotResolver(
        catalog=SnapshotCatalog(
            entries=(
                CatalogEntry(work_id="essay", names=("Essay",)),
                CatalogEntry(work_id="book", names=("Book",)),
            )
        ),
        snapshots=(TextSnapshot(endpoint=base, stream_id="body", text="Quote tail"),),
    )
    return SQLiteReferenceStore(tmp_path / "working.db", actor_id="reviewer"), ref, resolver


@pytest.mark.parametrize("origin", ["manual", "automatic"])
def test_shared_validation_review_and_durable_audit(tmp_path, origin):
    store, ref, resolver = fixture(tmp_path, origin)
    assert store.save(ref, expected_version=None) == 1
    assert (
        store.approve(
            ref.id, expected_version=1, resolver=resolver, reason="checked source and work"
        )
        == 2
    )
    assert store.get(ref.id).review == "approved"
    assert store.get(ref.id).resolution == "resolved"
    assert store.get(ref.id).publication == "draft"
    reopened = SQLiteReferenceStore(tmp_path / "working.db", actor_id="another")
    history = reopened.history(ref.id)
    assert [x.version for x in history] == [1, 2]
    assert history[0].reference == ref
    assert history[1].actor_id == "reviewer" and history[1].validation.source.status == "resolved"
    assert history[1].recorded_at.tzinfo is not None
    assert all(x.reference.id == ref.id for x in history)


def test_compare_and_swap_and_noop_edits(tmp_path):
    store, ref, _ = fixture(tmp_path)
    assert store.save(ref, expected_version=None) == 1
    assert store.save(ref, expected_version=1) == 1
    for version in (None, 2):
        with pytest.raises(VersionConflictError):
            store.save(ref, expected_version=version)
    other = SQLiteReferenceStore(tmp_path / "working.db", actor_id="other")
    other.reject(ref.id, expected_version=1, reason="not relevant")
    with pytest.raises(VersionConflictError):
        store.reject(ref.id, expected_version=1, reason="stale reviewer")
    assert len(store.history(ref.id)) == 2


def test_review_requires_validation_and_pending_state(tmp_path):
    store, ref, resolver = fixture(tmp_path)
    store.save(ref, expected_version=None)
    missing = SnapshotResolver(catalog=resolver.catalog)
    with pytest.raises(ValueError, match="verified current source"):
        store.approve(ref.id, expected_version=1, resolver=missing, reason="cannot verify")
    assert len(store.history(ref.id)) == 1
    store.reject(ref.id, expected_version=1, reason="rejected")
    with pytest.raises(ValueError, match="pending draft"):
        store.approve(ref.id, expected_version=2, resolver=resolver, reason="invalid transition")
    assert store.save(ref, expected_version=2, reason="resubmitted") == 3
    assert store.approve(ref.id, expected_version=3, resolver=resolver, reason="checked") == 4
    with pytest.raises(ValueError, match="pending draft"):
        store.reject(ref.id, expected_version=4, reason="must reopen")


def test_edits_invalidate_approval_and_cannot_import_publication(tmp_path):
    store, ref, resolver = fixture(tmp_path)
    store.save(ref, expected_version=None)
    store.approve(ref.id, expected_version=1, resolver=resolver, reason="checked")
    edited = Reference.model_validate({**ref.model_dump(), "relationship": "core:related"})
    store.save(edited, expected_version=2, reason="changed relationship")
    assert store.get(ref.id).review == "pending"
    published = Reference.model_validate(
        {**edited.model_dump(), "review": "approved", "publication": "published"}
    )
    with pytest.raises(ValueError, match="pending draft"):
        store.save(published, expected_version=3)


def test_unresolved_work_requires_explicit_acceptance(tmp_path):
    store, ref, resolver = fixture(tmp_path)
    ref = Reference.model_validate({**ref.model_dump(), "target": Endpoint(work_id="external")})
    store.save(ref, expected_version=None)
    with pytest.raises(ValueError, match="target must be verified"):
        store.approve(ref.id, expected_version=1, resolver=resolver, reason="no catalog match")
    store.approve(
        ref.id,
        expected_version=1,
        resolver=resolver,
        reason="retain external citation",
        allow_unresolved_target=True,
    )
    assert store.get(ref.id).resolution == "unresolved"
    assert store.get(ref.id).review == "approved"


def test_stale_physical_target_cannot_be_approved_by_override(tmp_path):
    store, ref, resolver = fixture(tmp_path)
    ref = Reference.model_validate({**ref.model_dump(), "target": ref.source})
    changed = TextSnapshot(
        endpoint=resolver.snapshots[0].endpoint, stream_id="body", text="Wrong tail"
    )
    bad = SnapshotResolver(catalog=resolver.catalog, snapshots=(changed,))
    store.save(ref, expected_version=None)
    with pytest.raises(ValueError):
        store.approve(
            ref.id, expected_version=1, resolver=bad, reason="stale", allow_unresolved_target=True
        )


def test_resolution_is_audited_and_separate_from_review(tmp_path):
    example = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "packages/linking/examples/resolve_link.py")
    )
    ref = example["resolve_link"]()
    store = SQLiteReferenceStore(tmp_path / "working.db", actor_id="resolver")
    store.save(ref, expected_version=None)
    missing = SnapshotResolver(catalog=SnapshotCatalog())
    store.resolve_target(ref.id, expected_version=1, resolver=missing, reason="asset unavailable")
    assert store.get(ref.id).resolution == "unresolved" and store.get(ref.id).review == "pending"
    assert store.history(ref.id)[1].validation.target.status == "unresolved"


def test_invalid_audit_and_versions_reject_without_writes(tmp_path):
    store, ref, _ = fixture(tmp_path)
    for reason in ("", " "):
        with pytest.raises(ValueError):
            store.save(ref, expected_version=None, reason=reason)
    for version in (True, 0, -1):
        with pytest.raises(ValueError):
            store.save(ref, expected_version=version)
    assert store.history(ref.id) == ()


def test_concurrent_reviewers_only_one_revision_commits(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store, ref, _ = fixture(tmp_path)
    store.save(ref, expected_version=None)
    barrier = Barrier(2)

    def review(actor):
        local = SQLiteReferenceStore(tmp_path / "working.db", actor_id=actor)
        barrier.wait(timeout=5)
        try:
            return local.reject(ref.id, expected_version=1, reason="reviewed")
        except VersionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(review, ("first", "second")))
    assert set(outcomes) == {2, "conflict"}
    assert len(store.history(ref.id)) == 2


def test_approval_cannot_override_unavailable_physical_target(tmp_path):
    store, ref, resolver = fixture(tmp_path)
    target = Endpoint.model_validate({**ref.source.model_dump(), "revision": "2"})
    ref = Reference.model_validate({**ref.model_dump(), "target": target})
    store.save(ref, expected_version=None)
    with pytest.raises(ValueError, match="target must be verified"):
        store.approve(
            ref.id,
            expected_version=1,
            resolver=resolver,
            reason="missing edition",
            allow_unresolved_target=True,
        )
    assert len(store.history(ref.id)) == 1


def test_conversion_evidence_survives_review_without_becoming_validation(tmp_path):
    from corpora_py.linking_conversion import ConvertedReference

    store, ref, resolver = fixture(tmp_path, "automatic")
    evidence = ConvertedReference(
        reference=ref, diagnostics=("original location mapping unavailable",)
    )
    store.save(ref, expected_version=None, conversion=evidence)
    store.approve(
        ref.id, expected_version=1, resolver=resolver, reason="reviewed converted selection"
    )
    assert all(x.conversion == evidence for x in store.history(ref.id))
    assert store.history(ref.id)[1].validation.source.status == "resolved"
    other = Reference.model_validate(
        {**ref.model_dump(), "id": "00000000-0000-0000-0000-000000000001"}
    )
    with pytest.raises(ValueError, match="another reference"):
        store.save(other, expected_version=None, conversion=evidence)


def test_ambiguous_target_cannot_be_approved_by_override(tmp_path):
    from corpora_linking import ResolutionResult

    store, ref, resolver = fixture(tmp_path)
    store.save(ref, expected_version=None)

    class AmbiguousResolver:
        def resolve(self, endpoint):
            if endpoint == ref.source:
                return resolver.resolve(endpoint)
            return ResolutionResult(
                status="ambiguous", candidates=(Endpoint(work_id="a"), Endpoint(work_id="b"))
            )

    with pytest.raises(ValueError, match="target must be verified"):
        store.approve(
            ref.id,
            expected_version=1,
            resolver=AmbiguousResolver(),
            reason="ambiguous",
            allow_unresolved_target=True,
        )


def test_citation_resolution_adopts_verified_endpoint_then_review(tmp_path):
    from corpora_linking import CitationLocator, PassageEntry

    store, ref, resolver = fixture(tmp_path, "automatic")
    citation = CitationLocator(
        value="Essay 1:1", profile="fixture", scheme_id="fixture", scheme_version="1"
    )
    request = Endpoint(work_id="essay", locators=(citation,))
    ref = Reference.model_validate({**ref.model_dump(), "target": request})
    resolver = SnapshotResolver(
        catalog=resolver.catalog,
        snapshots=resolver.snapshots,
        passages=(PassageEntry(citation=citation, target=ref.source),),
    )
    store.save(ref, expected_version=None)
    with pytest.raises(ValueError, match="target must be verified"):
        store.approve(ref.id, expected_version=1, resolver=resolver, reason="must adopt first")
    assert (
        store.resolve_target(
            ref.id, expected_version=1, resolver=resolver, reason="verified passage"
        )
        == 2
    )
    assert store.get(ref.id).target == ref.source
    assert store.get(ref.id).review == "pending"
    assert store.history(ref.id)[0].reference.target == request
    assert (
        store.approve(ref.id, expected_version=2, resolver=resolver, reason="reviewed exact target")
        == 3
    )
    assert all(x.reference.id == ref.id for x in store.history(ref.id))


def test_review_example_keeps_approval_separate_from_publication():
    example = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "packages/linking/examples/review_link.py")
    )
    history = example["review_link"]()
    assert [x.actor_id for x in history] == ["reader", "reviewer"]
    assert (
        history[-1].reference.review == "approved" and history[-1].reference.publication == "draft"
    )
