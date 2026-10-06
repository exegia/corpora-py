"""Resolve a curation selection within one already-authorized corpus snapshot."""

from __future__ import annotations

import hashlib
from typing import Any

from .schemas import NodeScope, ScopeLevel


def scope_nodes(api: Any, scope: NodeScope) -> tuple[int, ...]:
    """Expand a node or sibling range; never use numeric IDs as range order.

    A passage range is anchored either at its first unit (the original panel
    contract) or at a containing node. Its units must share one enclosing
    declared section. Crossing sections is rejected rather than silently
    widening the scope. Non-contiguous TF nodes are allowed.
    """
    otype = api.F.otype
    section_types = tuple(api.T.sectionTypes)

    def node_type(node: int) -> str:
        if not 1 <= node <= otype.maxNode or not (value := otype.v(node)):
            raise ValueError(f"Unknown node {node}")
        return str(value)

    def slots(node: int) -> set[int]:
        return {node} if node <= otype.maxSlot else set(map(int, api.E.oslots.s(node)))

    def order(node: int) -> tuple[int, int, int]:
        linked = slots(node)
        # Empty nodes must reach the validator so it can report OSLOTS_EMPTY.
        return (min(linked), -max(linked), node) if linked else (otype.maxSlot + 1, 0, node)

    if scope.level is ScopeLevel.corpus:
        if scope.node_id is not None or scope.unit_range is not None or scope.node_type is not None:
            raise ValueError("Corpus scope cannot carry a node, node type, or unit range")
        return tuple(range(1, otype.maxNode + 1))

    assert scope.node_id is not None  # NodeScope enforces this at the boundary.
    anchor = scope.node_id
    actual_type = node_type(anchor)
    if scope.node_type is not None and scope.node_type != actual_type:
        raise ValueError(f"Node {anchor} has type {actual_type!r}, not {scope.node_type!r}")
    if scope.level is ScopeLevel.word and anchor > otype.maxSlot:
        raise ValueError("Word scope requires a slot node")
    if scope.level is not ScopeLevel.word and anchor <= otype.maxSlot:
        raise ValueError("A structural scope requires a non-slot node")
    if scope.level is ScopeLevel.section and actual_type not in section_types:
        raise ValueError("Section scope requires a declared section type")
    if scope.level is ScopeLevel.document and (
        not section_types or actual_type != section_types[0]
    ):
        raise ValueError("Document scope requires the outermost declared section type")
    if scope.unit_range is not None and scope.level is not ScopeLevel.passage:
        raise ValueError("Only passage scope accepts a unit range")

    roots: tuple[int, ...] = (anchor,)
    if scope.unit_range is not None:
        start, end = scope.unit_range.start, scope.unit_range.end
        unit_type = node_type(start)
        if node_type(end) != unit_type or start <= otype.maxSlot or end <= otype.maxSlot:
            raise ValueError("Passage endpoints must be structural nodes of the same type")

        def parent(node: int) -> int:
            for kind in reversed(section_types):
                if kind == unit_type:
                    continue
                parents = tuple(api.L.u(node, otype=kind))
                if len(parents) > 1:
                    raise ValueError("Passage has ambiguous enclosing sections")
                if parents:
                    return int(parents[0])
            raise ValueError("Passage range requires an enclosing declared section")

        enclosing = parent(start)
        if enclosing != parent(end):
            raise ValueError("Passage range crosses a section boundary")
        siblings = sorted(
            (int(n) for n in api.L.d(enclosing, otype=unit_type) if parent(int(n)) == enclosing),
            key=order,
        )
        if start not in siblings or end not in siblings:
            raise ValueError("Passage endpoints must be contained in their section")
        first, last = siblings.index(start), siblings.index(end)
        if last < first:
            raise ValueError("Passage endpoints are reversed in document order")
        roots = tuple(siblings[first : last + 1])
        covered = set().union(*(slots(n) for n in roots))
        if anchor != start and not covered <= slots(anchor):
            raise ValueError("Passage anchor must contain the range or be its first unit")

    selected: set[int] = set(roots)
    for root in roots:
        if root > otype.maxSlot:
            selected.update(int(n) for n in api.L.d(root))
    return tuple(sorted(selected, key=order))


def scope_content_hash(api: Any, nodes: tuple[int, ...]) -> str:
    """SHA-256 of default-format text over unique selected slots, in slot order.

    No trimming, normalization, or inserted separators. This is a text hash,
    not a feature-diff guard; suggestion apply must also check old values.
    """
    slots = sorted(n for n in nodes if n <= api.F.otype.maxSlot)
    text = api.T.text(slots)
    if not isinstance(text, str):
        raise ValueError("Corpus has no usable default text format")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
