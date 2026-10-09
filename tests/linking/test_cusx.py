from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest
from corpora_linking import (
    Endpoint,
    Provenance,
    Reference,
    StructuralLocator,
    TextLocator,
    TextSnapshot,
)

from corpora_py.linking_cusx import (
    CX,
    STREAM,
    AnchorBinding,
    bind_cusx_anchors,
    cusx_text,
    publish_cusx_links,
)
from corpora_py.linking_publication import PublicationSnapshot, SnapshotEntry


def fixture():
    data = '<usx version="3.0"><para style="p">😀 See <char style="it">John</char> 3:16.</para><para style="p">Next</para></usx>'.encode()
    endpoint = Endpoint(work_id="w", edition_id="e", package_id="p", revision="1", document_id="d")
    snapshot = TextSnapshot(endpoint=endpoint, stream_id=STREAM, text=cusx_text(data))
    quote = "See John 3:16"
    start = snapshot.text.index(quote)
    selection = endpoint.model_copy(
        update={
            "locators": (
                TextLocator(
                    stream_id=STREAM,
                    start=start,
                    end=start + len(quote),
                    exact=quote,
                    prefix="😀 ",
                    suffix=".",
                ),
            )
        }
    )
    return data, snapshot, selection


def test_cross_node_boundaries_preserve_text_without_paragraph_ids():
    data, snapshot, selection = fixture()
    binding = AnchorBinding(selection=selection, anchor_id="passage-opaque")
    output = bind_cusx_anchors(data, snapshot, (binding,))
    assert cusx_text(output) == snapshot.text
    root = ET.fromstring(output)
    boundaries = root.findall(f".//{{{CX}}}boundary")
    assert boundaries[0].get(f"{{{CX}}}id") == "passage-opaque"
    assert boundaries[1].get("eid") == "passage-opaque"
    assert all(paragraph.get(f"{{{CX}}}id") is None for paragraph in root.findall("para"))
    with pytest.raises(ValueError, match="duplicate"):
        bind_cusx_anchors(output, snapshot, (binding,))
    with pytest.raises(ValueError, match="differs"):
        bind_cusx_anchors(data.replace(b"John", b"Gone"), snapshot, (binding,))


def test_jmp_fragments_keep_reference_id_and_inline_structure():
    data, snapshot, source = fixture()
    reference = Reference(
        id=uuid4(),
        source=source,
        target=snapshot.endpoint.model_copy(
            update={"locators": (StructuralLocator(anchor_id="verse"),)}
        ),
        provenance=Provenance(origin="manual", agent_id="reader", method="selection"),
        resolution="resolved",
        review="approved",
        publication="published",
    )
    publication = PublicationSnapshot(
        authority_id="fixture", entries=(SnapshotEntry(reference=reference),)
    )
    output = publish_cusx_links(data, snapshot, publication)
    assert cusx_text(output) == snapshot.text
    root = ET.fromstring(output)
    links = [element for element in root.iter("char") if element.get("style") == "jmp"]
    assert "".join(element.text for element in links) == "See John 3:16"
    assert {element.get("link-id") for element in links} == {f"urn:uuid:{reference.id}"}
    assert root.find('.//char[@style="it"]/char[@style="jmp"]').text == "John"
    with pytest.raises(ValueError, match="already embedded"):
        publish_cusx_links(output, snapshot, publication)
    overlapping = reference.model_copy(update={"id": uuid4()})
    with pytest.raises(ValueError, match="overlapping"):
        publish_cusx_links(
            data,
            snapshot,
            publication.model_copy(
                update={
                    "entries": (
                        SnapshotEntry(reference=reference),
                        SnapshotEntry(reference=overlapping),
                    )
                }
            ),
        )


def test_text_destination_needs_explicit_binding_and_retains_sidecar_evidence():
    data, snapshot, source = fixture()
    reference = Reference(
        source=source,
        target=source,
        provenance=Provenance(origin="manual", agent_id="reader", method="selection"),
        resolution="resolved",
        review="approved",
        publication="published",
    )
    publication = PublicationSnapshot(
        authority_id="fixture", entries=(SnapshotEntry(reference=reference),)
    )
    with pytest.raises(ValueError, match="explicit"):
        publish_cusx_links(data, snapshot, publication)
    binding = AnchorBinding(selection=source, anchor_id="chosen")
    output = publish_cusx_links(data, snapshot, publication, target_bindings=(binding,))
    assert b"#chosen" in output
    assert publication.entries[0].reference.target == source


def test_advertised_binding_checks_exact_range_not_just_anchor_name():
    from corpora_py.linking_cusx import validate_cusx_binding

    data, snapshot, selection = fixture()
    binding = AnchorBinding(selection=selection, anchor_id="chosen")
    output = bind_cusx_anchors(data, snapshot, (binding,))
    validate_cusx_binding(output, snapshot, binding)
    with pytest.raises(ValueError, match="missing"):
        validate_cusx_binding(data, snapshot, binding)
    locator = selection.locators[0]
    shortened = selection.model_copy(
        update={
            "locators": (
                locator.model_copy(
                    update={"end": locator.end - 1, "exact": locator.exact[:-1], "suffix": ""}
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="offsets"):
        validate_cusx_binding(output, snapshot, binding.model_copy(update={"selection": shortened}))


def test_native_cusx_range_retrieves_cross_node_passage_and_rejects_broken_pair():
    from corpora_py.linking_cusx import retrieve_cusx_selection

    data, snapshot, selection = fixture()
    binding = AnchorBinding(selection=selection, anchor_id="chosen")
    output = bind_cusx_anchors(data, snapshot, (binding,))
    target = snapshot.endpoint.model_copy(
        update={"locators": (StructuralLocator(anchor_id="chosen"),)}
    )
    assert retrieve_cusx_selection(output, target) == selection.locators[0].exact
    with pytest.raises(ValueError, match="missing"):
        retrieve_cusx_selection(output.replace(b'eid="chosen"', b'eid="other"'), target)
