import json

import pytest
from corpora_linking import (
    CatalogEntry,
    Endpoint,
    Provenance,
    PublicationAdapter,
    Reference,
    SnapshotCatalog,
    SnapshotResolver,
    TextLocator,
    TextSnapshot,
)

from corpora_py.linking_publication import PublicationSnapshot, SnapshotPublicationAdapter
from corpora_py.linking_store import SQLiteReferenceStore, VersionConflictError


def fixture(tmp_path):
    base = Endpoint(work_id="essay", edition_id="e", package_id="p", revision="1", document_id="d")
    source = Endpoint.model_validate(
        {
            **base.model_dump(),
            "locators": [TextLocator(stream_id="body", start=0, end=5, exact="Quote")],
        }
    )
    ref = Reference(
        source=source,
        target=Endpoint(work_id="book"),
        provenance=Provenance(origin="manual", agent_id="reader", method="selection"),
    )
    resolver = SnapshotResolver(
        catalog=SnapshotCatalog(
            entries=(
                CatalogEntry(work_id="essay", names=("Essay",)),
                CatalogEntry(work_id="book", names=("Book",)),
            )
        ),
        snapshots=(TextSnapshot(endpoint=base, stream_id="body", text="Quote"),),
    )
    store = SQLiteReferenceStore(tmp_path / "source.db", actor_id="reviewer")
    store.save(ref, expected_version=None)
    store.approve(ref.id, expected_version=1, resolver=resolver, reason="verified")
    adapter = SnapshotPublicationAdapter("fixture:source-database")
    return store, ref, adapter


def test_approved_export_preserves_ids_versions_and_working_state(tmp_path):
    store, ref, adapter = fixture(tmp_path)
    before = store.history(ref.id)
    payload = adapter.export_working(store, (ref.id,))
    snapshot = PublicationSnapshot.model_validate_json(payload)
    assert snapshot.entries[0].reference.id == ref.id
    assert snapshot.entries[0].working_version == 2
    assert snapshot.entries[0].reference.publication == "published"
    assert store.history(ref.id) == before
    assert store.get(ref.id).publication == "draft"
    assert adapter.export_working(store, (ref.id,)) == payload
    protocol: PublicationAdapter = adapter
    (imported,) = protocol.import_references(payload)
    assert imported.id == ref.id and imported.review == "pending"
    assert imported.publication == "draft" and imported.resolution == "unresolved"


def test_unapproved_withdrawn_duplicates_and_unknown_schema_reject(tmp_path):
    store, ref, adapter = fixture(tmp_path)
    with pytest.raises(ValueError, match="approved"):
        adapter.export((ref,))
    approved = store.get(ref.id)
    withdrawn = Reference.model_validate({**approved.model_dump(), "publication": "withdrawn"})
    with pytest.raises(ValueError, match="non-withdrawn"):
        adapter.export((withdrawn,))
    with pytest.raises(ValueError, match="duplicate"):
        adapter.export((approved, approved))
    data = json.loads(adapter.export_working(store, (ref.id,)))
    data["schema_version"] = "unknown"
    with pytest.raises(ValueError):
        adapter.import_references(json.dumps(data).encode())


def test_import_new_then_idempotent_without_approval(tmp_path):
    store, ref, adapter = fixture(tmp_path)
    target = SQLiteReferenceStore(tmp_path / "target.db", actor_id="importer")
    payload = adapter.export_working(store, (ref.id,))
    (decision,) = adapter.plan_import(payload, target)
    assert decision.outcome == "create"
    assert adapter.apply_import(decision, target, reason="import fixture") == 1
    assert target.get(ref.id).review == "pending"
    assert target.get(ref.id).publication == "draft"
    assert target.history(ref.id)[0].actor_id == "importer"
    assert "upstream_version=2" in target.history(ref.id)[0].reason
    (again,) = adapter.plan_import(payload, target)
    assert again.outcome == "unchanged"
    assert adapter.apply_import(again, target, reason="same snapshot") == 1
    assert len(target.history(ref.id)) == 1


def test_conflicting_or_stale_snapshot_never_overwrites_working_state(tmp_path):
    store, ref, adapter = fixture(tmp_path)
    payload = adapter.export_working(store, (ref.id,))
    before = store.history(ref.id)
    changed = Reference.model_validate({**ref.model_dump(), "relationship": "core:related"})
    store.save(changed, expected_version=2, reason="newer working edit")
    (decision,) = adapter.plan_import(payload, store)
    assert decision.outcome == "conflict" and decision.expected_version == 3
    with pytest.raises(ValueError, match="conflicting"):
        adapter.apply_import(decision, store, reason="do not overwrite")
    assert store.get(ref.id) == changed
    assert store.history(ref.id)[:2] == before


def test_import_plan_races_and_local_versions_are_checked(tmp_path):
    store, ref, adapter = fixture(tmp_path)
    payload = adapter.export_working(store, (ref.id,))
    (decision,) = adapter.plan_import(payload, store)
    assert decision.outcome == "unchanged"
    store.save(ref, expected_version=2, reason="reopen review")
    with pytest.raises(VersionConflictError):
        adapter.apply_import(decision, store, reason="stale plan")
    other = SQLiteReferenceStore(tmp_path / "target.db", actor_id="importer")
    (create,) = adapter.plan_import(payload, other)
    other.save(ref, expected_version=None)
    with pytest.raises(VersionConflictError):
        adapter.apply_import(create, other, reason="stale create")


def test_distinct_ids_with_identical_content_are_not_deduplicated(tmp_path):
    store, ref, adapter = fixture(tmp_path)
    approved = store.get(ref.id)
    another = Reference.model_validate(
        {**approved.model_dump(), "id": "00000000-0000-0000-0000-000000000001"}
    )
    payload = adapter.export((approved, another))
    target = SQLiteReferenceStore(tmp_path / "target.db", actor_id="importer")
    for decision in adapter.plan_import(payload, target):
        adapter.apply_import(decision, target, reason="distinct attribution")
    assert target.get(ref.id) is not None and target.get(another.id) is not None


def test_existing_cusx_jump_uses_matching_ids_and_encoded_scope(tmp_path):
    from xml.etree import ElementTree

    from corpora_linking import StructuralLocator

    from corpora_py.linking_publication import render_cusx_jump

    store, ref, adapter = fixture(tmp_path)
    target = Endpoint(
        work_id="book",
        edition_id="e",
        package_id="a/b",
        revision="rev#1",
        document_id="doc?é",
        locators=(StructuralLocator(anchor_id="part/a#1"),),
    )
    approved = Reference.model_validate({**store.get(ref.id).model_dump(), "target": target})
    snapshot = PublicationSnapshot.model_validate_json(adapter.export((approved,)))
    (entry,) = snapshot.entries
    element = ElementTree.fromstring(render_cusx_jump(entry))
    assert element.tag == "char" and element.get("style") == "jmp"
    assert element.get("link-id") == f"urn:uuid:{ref.id}"
    assert element.get("link-href") == "x-corpora:/a%2Fb/rev%231/doc%3F%C3%A9#part%2Fa%231"
    assert element.text == ref.source.locators[0].exact


def test_cusx_rendering_does_not_invent_anchors_for_unsupported_targets(tmp_path):
    from corpora_py.linking_publication import render_cusx_jump

    store, ref, adapter = fixture(tmp_path)
    (entry,) = PublicationSnapshot.model_validate_json(
        adapter.export_working(store, (ref.id,))
    ).entries
    with pytest.raises(ValueError, match="concrete package"):
        render_cusx_jump(entry)
    text_target = Reference.model_validate({**store.get(ref.id).model_dump(), "target": ref.source})
    (entry,) = PublicationSnapshot.model_validate_json(adapter.export((text_target,))).entries
    with pytest.raises(ValueError, match="explicit published anchor"):
        render_cusx_jump(entry)


def test_snapshot_example_preserves_ids_and_import_needs_review():
    import runpy
    from pathlib import Path

    example = runpy.run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "packages/linking/examples/publication_roundtrip.py"
        )
    )
    payload, history = example["publication_roundtrip"]()
    snapshot = PublicationSnapshot.model_validate_json(payload)
    assert snapshot.entries[0].reference.id == history[0].reference.id
    assert history[0].reference.review == "pending" and len(history) == 1


def test_cusx_unresolved_destinations_and_xml_controls_reject(tmp_path):
    from corpora_py.linking_publication import render_cusx_jump

    store, ref, adapter = fixture(tmp_path)
    approved = Reference.model_validate(
        {**store.get(ref.id).model_dump(), "resolution": "unresolved"}
    )
    (entry,) = PublicationSnapshot.model_validate_json(adapter.export((approved,))).entries
    with pytest.raises(ValueError, match="no exact C-USX"):
        render_cusx_jump(entry)
    target = Endpoint(work_id="book", edition_id="e", package_id="p", revision="1", document_id="d")
    for quote, expected in (("<&>", "<&>"), ("a\f", None)):
        source = Endpoint.model_validate(
            {
                **ref.source.model_dump(),
                "locators": [TextLocator(stream_id="body", start=0, end=len(quote), exact=quote)],
            }
        )
        approved = Reference.model_validate(
            {**store.get(ref.id).model_dump(), "source": source, "target": target}
        )
        (entry,) = PublicationSnapshot.model_validate_json(adapter.export((approved,))).entries
        if expected is None:
            with pytest.raises(ValueError, match="XML 1.0"):
                render_cusx_jump(entry)
        else:
            from xml.etree import ElementTree

            assert ElementTree.fromstring(render_cusx_jump(entry)).text == expected
