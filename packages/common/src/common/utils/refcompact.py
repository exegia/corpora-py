"""Compact positional token — a *serialization* of a resolved reference.

The citation string the UI shows, stores and resolves is the `tfref` short
form (`bhsa@2021/Deut:4:2!clause1`, see `common.utils.tfref`). The compact
form specified in `docs/architecture/inter-corpus-refs.md`
(`co<corpus>_bk001_ch004_pa002_cl001`) is kept as a second, machine-oriented
encoding of the *same resolved node*: a single `[a-z0-9_-]` token with no
headings, no `:`/`!`/`@`, safe in URL fragments, annotation bodies and
filenames. It is lossless only against the corpus that produced it, so it
always carries the corpus id and is meant to be produced from a node and
translated back through the corpus -- never hand-written.

Deviations from the draft spec, all recorded in that document:

* the corpus id is the library slug (`comobydick`), not a 4-hex tail;
* level prefixes bind by *position* in `T.sectionTypes` (1st level = `bk`,
  2nd = `ch`, 3rd = `pa`), so `volume/chapter/paragraph` corpora work too;
* `ph` (phrase) joins `st`/`cl`/`wo`, and a sub-unit ordinal may carry an
  inclusive range (`wo003-005`), mirroring `tfref`'s `!word3-5`;
* ordinals are 1-based positions in canonical order under the nearest
  *present* ancestor, using tfref's anchor-to-first-slot rule -- the same
  numbers `!clause1` uses, so the two forms never disagree about a node.
"""

from __future__ import annotations

import re

from .tfref import Adapter, IndexOutOfRange, ParseError, SectionNotFound, TypeNotInSection

SECTION_PREFIXES = ("bk", "ch", "pa")  # by section depth, outermost first
# `pa` is overloaded on purpose (spec open issue 4): it is the 3rd section
# level when the corpus declares one, else the block-level node type that
# sits under the innermost section (this repo's converters emit `paragraph`
# nodes under a single `book` section).
UNIT_PREFIXES = {
    "sentence": "st",
    "clause": "cl",
    "phrase": "ph",
    "word": "wo",
    "paragraph": "pa",
    "para": "pa",
    "verse": "pa",
}
_BLOCK_TYPES = ("paragraph", "para", "verse")
_UNIT_TYPES = {"st": "sentence", "cl": "clause", "ph": "phrase", "wo": "word"}
_ALL_PREFIXES = "|".join(SECTION_PREFIXES + ("st", "cl", "ph", "wo"))

_TOKEN_RE = re.compile(
    rf"^co(?P<corpus>[a-z0-9][a-z0-9.-]*)(?P<levels>(?:_(?:{_ALL_PREFIXES})\d+(?:-\d+)?)*)$"
)
_LEVEL_RE = re.compile(rf"_(?P<prefix>{_ALL_PREFIXES})(?P<i>\d+)(?:-(?P<j>\d+))?")


def is_compact(token: str) -> bool:
    return bool(_TOKEN_RE.match(token.strip()))


def slug_of(token: str) -> str:
    """The corpus slug a compact token carries (no corpus needed)."""
    m = _TOKEN_RE.match(token.strip())
    if not m:
        raise ParseError(f"Not a compact reference token: {token!r}.")
    return m.group("corpus")


def corpus_slug(corpus_id: str) -> str:
    """Library ids may contain `_`, the token separator; fold to `-`."""
    return corpus_id.lower().replace("_", "-")


def _top_nodes(adapter: Adapter, stype: str) -> list[int]:
    """All nodes of the outermost section type, canonical order."""
    api = getattr(adapter, "api", None)
    if api is not None:
        nodes = [int(n) for n in api.F.otype.s(stype)]
    else:
        by_first = getattr(adapter, "_by_first", {})
        nodes = [n for _, _, n in by_first.get(stype, [])]
    return sorted(nodes, key=lambda n: adapter.slots(n))


def _pad(i: int) -> str:
    return f"{i:03d}"


def to_compact(node: int | list[int], adapter: Adapter, corpus_id: str) -> str:
    """Node (or [first, last] of one otype) -> `co<slug>_bk001_..._cl001`."""
    first = node[0] if isinstance(node, list) else node
    last = node[-1] if isinstance(node, list) else node
    otype = adapter.otype(first)
    if not otype:
        raise SectionNotFound(f"Node {first} does not exist.")
    if isinstance(node, list) and adapter.otype(last) != otype:
        raise TypeNotInSection("A range must consist of nodes of one type.")

    parts = [f"co{corpus_slug(corpus_id)}"]
    slot, _ = adapter.slots(first)
    headings = adapter.section_from_node(slot)
    parent: int | None = None
    is_section = otype in adapter.section_types
    depth_of_node = adapter.section_types.index(otype) + 1 if is_section else None
    for depth, stype in enumerate(adapter.section_types, 1):
        if depth > len(SECTION_PREFIXES):
            break
        if depth_of_node is not None and depth > depth_of_node:
            break
        key = tuple(headings[:depth])
        if None in key:
            break  # gap at this level: address from the last present ancestor
        sec_node = adapter.node_from_section(key)
        if sec_node is None:
            break
        siblings = _top_nodes(adapter, stype) if parent is None else adapter.children(parent, stype)
        try:
            ordinal = siblings.index(sec_node) + 1
        except ValueError as exc:
            raise SectionNotFound(f"Section node {sec_node} is not under node {parent}.") from exc
        parts.append(f"{SECTION_PREFIXES[depth - 1]}{_pad(ordinal)}")
        parent = sec_node
    if len(parts) == 1:
        raise SectionNotFound(f"Node {first} is not inside any section.")
    if is_section:
        return "_".join(parts)

    prefix = UNIT_PREFIXES.get(otype)
    if prefix is None:
        raise TypeNotInSection(
            f"No compact prefix for node type {otype!r}; supported: {sorted(UNIT_PREFIXES)}."
        )
    assert parent is not None
    if prefix == "pa" and len(parts) - 1 >= len(SECTION_PREFIXES):
        raise TypeNotInSection(
            f"{otype!r} nodes cannot be encoded: `pa` is already the corpus's 3rd section level."
        )
    i = adapter.index_of(parent, otype, first)
    j = adapter.index_of(parent, otype, last)
    unit = f"{prefix}{_pad(i)}" + (f"-{_pad(j)}" if j != i else "")
    return "_".join(parts + [unit])


def from_compact(token: str, adapter: Adapter) -> tuple[str, int | list[int]]:
    """`co<slug>_bk001_..._cl001` -> (corpus slug, node or node list).

    Skipped levels count under the nearest present ancestor, as the spec
    requires: `cox_bk001_pa034` is the 34th paragraph-level section of the
    book, whichever chapter it falls in.
    """
    m = _TOKEN_RE.match(token.strip())
    if not m:
        raise ParseError(
            f"Not a compact reference token: {token!r} (expected co<slug>_bk001[_ch001][_pa001][_cl001])."
        )
    corpus = m.group("corpus")
    levels = [
        (lm.group("prefix"), int(lm.group("i")), lm.group("j"))
        for lm in _LEVEL_RE.finditer(m.group("levels"))
    ]
    if not levels:
        raise ParseError(f"{token!r} names a corpus but no level.")

    current: int | None = None
    seen_depth = 0
    for pos, (prefix, i, j) in enumerate(levels):
        is_last = pos == len(levels) - 1
        as_block = prefix == "pa" and len(adapter.section_types) < 3
        if prefix in SECTION_PREFIXES and not as_block:
            depth = SECTION_PREFIXES.index(prefix) + 1
            if depth <= seen_depth:
                raise ParseError(f"Level {prefix!r} out of order in {token!r}.")
            if depth > len(adapter.section_types):
                raise SectionNotFound(
                    f"{prefix!r} needs section level {depth} but this corpus has {len(adapter.section_types)}."
                )
            stype = adapter.section_types[depth - 1]
            siblings = (
                _top_nodes(adapter, stype) if current is None else adapter.children(current, stype)
            )
            if j is not None:
                raise ParseError(
                    f"Ranges are only allowed on the innermost unit ({prefix}{i}-{j})."
                )
            if not 1 <= i <= len(siblings):
                raise IndexOutOfRange(
                    f"{prefix}{i}: only {len(siblings)} {stype!r} node(s) at that position."
                )
            current = siblings[i - 1]
            seen_depth = depth
            continue

        otype = _UNIT_TYPES.get(prefix) or next(
            (t for t in _BLOCK_TYPES if t in adapter.all_types()), "paragraph"
        )
        if current is None:
            raise ParseError(f"{token!r} starts with a sub-unit; a section level must come first.")
        if otype not in adapter.all_types():
            raise TypeNotInSection(f"No node type {otype!r} in this corpus.")
        kids = adapter.children(current, otype)
        if not kids:
            raise TypeNotInSection(f"No {otype!r} nodes under node {current}.")
        end = int(j) if j is not None else i
        if j is not None and not is_last:
            raise ParseError(f"Ranges are only allowed on the innermost unit ({prefix}{i}-{j}).")
        if end < i or not 1 <= end <= len(kids):
            raise IndexOutOfRange(
                f"{prefix}{i}{'-' + j if j else ''}: node has {len(kids)} {otype!r} node(s)."
            )
        if j is not None:
            return corpus, list(kids[i - 1 : end])
        current = kids[i - 1]
    assert current is not None
    return corpus, current
