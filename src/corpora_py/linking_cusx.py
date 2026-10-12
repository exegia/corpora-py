"""Explicit C-USX text anchor publication without paragraph/sentence identifiers.

Stream: XML text and tails in document order, verbatim Unicode scalars; no
synthetic separators. Input must be a pinned converted snapshot of that stream.
Native-format selections require reviewed conversion mappings before this step.
"""

from collections.abc import Iterable
from xml.etree import ElementTree as ET

from corpora_linking import Endpoint, StructuralLocator, TextLocator, TextSnapshot
from corpora_linking.models import NonEmpty, Value
from lxml import etree

from .linking_publication import PublicationSnapshot, SnapshotEntry, render_cusx_jump

CX = "urn:corpora:usx-extension:0.1"
STREAM = "cusx-itertext/v1"


class AnchorBinding(Value):
    selection: Endpoint
    anchor_id: NonEmpty


def _tree(data: bytes):
    if b"<!DOCTYPE" in data.upper():
        raise ValueError("C-USX DOCTYPE is unsupported")
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    if root.tag != "usx":
        raise ValueError("expected a USX document")
    return root


def _slots(root):
    """Yield text/tail ownership in XML text order, excluding comment bodies."""
    if isinstance(root.tag, str) and root.text:
        yield root, "text", root.text
    for child in root:
        if isinstance(child.tag, str):
            yield from _slots(child)
        if child.tail:
            yield child, "tail", child.tail


def cusx_text(data: bytes) -> str:
    return "".join(text for _, _, text in _slots(_tree(data)))


def _selector(endpoint: Endpoint, snapshot: TextSnapshot) -> TextLocator:
    from corpora_linking import verify_text_anchor

    if (
        len(endpoint.locators) != 1
        or not isinstance(endpoint.locators[0], TextLocator)
        or snapshot.stream_id != STREAM
    ):
        raise ValueError("publication requires one C-USX stream text selection")
    locator = endpoint.locators[0]
    # Use the public verifier; never search for another occurrence.
    if (
        endpoint.model_copy(update={"locators": ()}) != snapshot.endpoint
        or locator.stream_id != snapshot.stream_id
        or locator.normalization != "preserve"
        or verify_text_anchor(
            locator,
            snapshot.text,
            expected_revision=endpoint.revision or "",
            actual_revision=snapshot.endpoint.revision or "",
        )
        != "valid"
    ):
        raise ValueError("publication selection does not match pinned C-USX text")
    return locator


def bind_cusx_anchors(
    data: bytes, snapshot: TextSnapshot, bindings: Iterable[AnchorBinding]
) -> bytes:
    """Insert paired cx:boundary anchors, preserving existing text and structure.

    IDs are supplied explicitly by the publication authority, unique in this
    document. A binding does not modify the working reference or its evidence.
    """
    root = _tree(data)
    slots = list(_slots(root))
    if "".join(text for _, _, text in slots) != snapshot.text:
        raise ValueError("C-USX text differs from pinned snapshot")
    existing = {
        element.get(f"{{{CX}}}id") for element in root.iter() if isinstance(element.tag, str)
    }
    cuts: dict[int, list[etree._Element]] = {}
    for binding in bindings:
        binding = AnchorBinding.model_validate(binding.model_dump())
        locator = _selector(binding.selection, snapshot)
        if binding.anchor_id in existing:
            raise ValueError("duplicate published anchor ID")
        existing.add(binding.anchor_id)
        start = etree.Element(f"{{{CX}}}boundary", nsmap={"cx": CX})
        start.attrib.update(
            {
                "unit": "passage",
                "scheme": STREAM,
                "sid": binding.anchor_id,
                f"{{{CX}}}id": binding.anchor_id,
            }
        )
        end = etree.Element(f"{{{CX}}}boundary", nsmap={"cx": CX})
        end.attrib.update({"unit": "passage", "scheme": STREAM, "eid": binding.anchor_id})
        cuts.setdefault(locator.start, []).append(start)
        cuts.setdefault(locator.end, []).insert(0, end)
    offset = 0
    for owner, attribute, text in slots:
        points = sorted(point for point in cuts if offset <= point <= offset + len(text))
        if points:
            local = [(point - offset, cuts.pop(point)) for point in points]
            setattr(owner, attribute, text[: local[0][0]])
            if attribute == "text":
                parent, index = owner, 0
            else:
                parent = owner.getparent()
                index = parent.index(owner) + 1
            for position, (point, elements) in enumerate(local):
                for element in elements:
                    parent.insert(index, element)
                    index += 1
                next_point = local[position + 1][0] if position + 1 < len(local) else len(text)
                elements[-1].tail = text[point:next_point]
        offset += len(text)
    if cuts:
        raise ValueError("anchor offset outside document text")
    output = etree.tostring(root, encoding="utf-8")
    if cusx_text(output) != snapshot.text:
        raise ValueError("anchor insertion changed document text")
    return output


def publish_cusx_links(
    data: bytes,
    snapshot: TextSnapshot,
    publication: PublicationSnapshot,
    *,
    target_bindings: Iterable[AnchorBinding] = (),
) -> bytes:
    """Place approved USX jmp links into exact source selections.

    Cross-element selections become several jmp fragments with one stable link
    ID; text/structure are preserved. Target text selections need an explicit
    binding already advertised in the target published document. Lossless original
    selections remain in the accompanying PublicationSnapshot, authoritative IDs
    unchanged. This function prepares an artifact, never acknowledges delivery.
    """
    publication = PublicationSnapshot.model_validate(publication.model_dump())
    bindings = tuple(target_bindings)
    root = _tree(data)
    slots = list(_slots(root))
    if "".join(text for _, _, text in slots) != snapshot.text:
        raise ValueError("C-USX text differs from pinned snapshot")
    selections: list[tuple[TextLocator, dict[str, str]]] = []
    for entry in publication.entries:
        reference = entry.reference
        if reference.source.model_copy(update={"locators": ()}) != snapshot.endpoint:
            continue  # Snapshot may cover other source documents.
        locator = _selector(reference.source, snapshot)
        target = reference.target
        if target.locators and not all(isinstance(x, StructuralLocator) for x in target.locators):
            matched = [binding for binding in bindings if binding.selection == target]
            if len(matched) != 1:
                raise ValueError("target selection requires one explicit published anchor binding")
            target = Endpoint.model_validate(
                {
                    **target.model_dump(),
                    "locators": (StructuralLocator(anchor_id=matched[0].anchor_id),),
                }
            )
        rendered = render_cusx_jump(
            SnapshotEntry(reference=reference.model_copy(update={"target": target}))
        )
        attributes = ET.fromstring(rendered).attrib
        if any(
            locator.start < previous.end and previous.start < locator.end
            for previous, _ in selections
        ):
            raise ValueError("overlapping source links require explicit editorial reconciliation")
        if any(element.get("link-id") == attributes["link-id"] for element in root.iter()):
            raise ValueError("reference is already embedded in this artifact")
        selections.append((locator, attributes))
    offset = 0
    for owner, attribute, text in slots:
        fragments = []
        for locator, attributes in selections:
            start, end = max(locator.start - offset, 0), min(locator.end - offset, len(text))
            if start < end:
                fragments.append((start, end, attributes))
        fragments.sort(key=lambda fragment: fragment[0])
        if fragments:
            setattr(owner, attribute, text[: fragments[0][0]])
            if attribute == "text":
                parent, index = owner, 0
            else:
                parent = owner.getparent()
                index = parent.index(owner) + 1
            for position, (start, end, attributes) in enumerate(fragments):
                element = etree.Element("char", attributes)
                element.text = text[start:end]
                next_start = (
                    fragments[position + 1][0] if position + 1 < len(fragments) else len(text)
                )
                element.tail = text[end:next_start]
                parent.insert(index, element)
                index += 1
        offset += len(text)
    output = etree.tostring(root, encoding="utf-8")
    if cusx_text(output) != snapshot.text:
        raise ValueError("link insertion changed document text")
    return output


def validate_cusx_binding(data: bytes, snapshot: TextSnapshot, binding: AnchorBinding) -> None:
    """Verify an advertised paired anchor against its pinned selection, not its name."""
    locator = _selector(binding.selection, snapshot)
    root = _tree(data)
    if cusx_text(data) != snapshot.text:
        raise ValueError("target document text differs from snapshot")
    positions = []
    offset = 0

    def walk(element):
        nonlocal offset
        if element.tag == f"{{{CX}}}boundary":
            if element.get("sid") == binding.anchor_id:
                if element.get(f"{{{CX}}}id") != binding.anchor_id:
                    raise ValueError("range start does not advertise anchor")
                positions.append(("start", offset))
            if element.get("eid") == binding.anchor_id:
                positions.append(("end", offset))
        if isinstance(element.tag, str) and element.text:
            offset += len(element.text)
        for child in element:
            if isinstance(child.tag, str):
                walk(child)
            if child.tail:
                offset += len(child.tail)

    walk(root)
    if positions != [("start", locator.start), ("end", locator.end)]:
        raise ValueError("published anchor is missing, duplicated or at different offsets")


def retrieve_cusx_selection(data: bytes, endpoint: Endpoint) -> str:
    """Retrieve a uniquely advertised structural or paired-boundary anchor."""
    if len(endpoint.locators) != 1 or not isinstance(endpoint.locators[0], StructuralLocator):
        raise ValueError("C-USX retrieval requires one structural anchor")
    anchor_id = endpoint.locators[0].anchor_id
    root = _tree(data)
    matches = [element for element in root.iter() if element.get(f"{{{CX}}}id") == anchor_id]
    if len(matches) != 1:
        raise ValueError("C-USX anchor is missing or ambiguous")
    start = matches[0]
    if start.tag != f"{{{CX}}}boundary":
        return "".join(text for _, _, text in _slots(start))
    if start.get("sid") != anchor_id:
        raise ValueError("C-USX boundary does not identify a range start")
    text = cusx_text(data)
    positions = []
    offset = 0

    def walk(element):
        nonlocal offset
        if element.tag == f"{{{CX}}}boundary":
            if element.get("sid") == anchor_id:
                positions.append(("start", offset))
            if element.get("eid") == anchor_id:
                positions.append(("end", offset))
        if isinstance(element.tag, str) and element.text:
            offset += len(element.text)
        for child in element:
            if isinstance(child.tag, str):
                walk(child)
            if child.tail:
                offset += len(child.tail)

    walk(root)
    if len(positions) != 2 or [kind for kind, _ in positions] != ["start", "end"]:
        raise ValueError("C-USX boundary pair is missing, ambiguous or reversed")
    return text[positions[0][1] : positions[1][1]]
