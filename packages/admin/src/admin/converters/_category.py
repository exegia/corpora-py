"""
Corpus categorization (issue #176) + the section specs each category implies
(issue #174).

Every conversion classifies its parsed `Document` tree into a
`CorpusCategory` — written to ``manifest.category`` and used to pick the
Text-Fabric section levels the dataset declares:

- ``document`` — one section level (the root, labeled by `title`).
- ``book``     — root + chapters (labeled by `label`).
- ``religious``— book/chapter/verse divisions under the root.

Detection reads structural roles off the parsed units (`section_role`):
explicit `book`/`chapter`/`verse` unit types, TEI ``<div type="...">``
attributes (including ``surah``), and level-1 markdown headings from the
PDF route (issue #175). A client may override via the `category` form field
on `POST /convert`, but an override the source can't support (religious
with no verses, book with no chapters) is *downgraded* to what the
structure carries, with a warning surfaced on the job log — declaring a TF
section level with no nodes would break the walk. For the same reason the
spec only declares the levels whose roles actually occur (a single-book
bible with no ``book`` divisions gets root/chapter/verse).

`categorize()` is the one converter-facing entry point; the helpers are
exposed for tests.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator

from ..parsers.schema import CorpusCategory, Document, Unit
from ._walker import SectionSpec, TypeMapper

# How much structure each category presumes. Used to cap an override at
# what the parsed structure (and the converter's vocabulary) can express.
_RANK = {
    CorpusCategory.DOCUMENT: 0,
    CorpusCategory.BOOK: 1,
    CorpusCategory.RELIGIOUS: 2,
}

_CHAPTER_ATTR_TYPES = frozenset({"chapter", "surah"})


def _iter_units(documents: Iterable[Document]) -> Iterator[Unit]:
    stack: list[Unit] = [unit for document in documents for unit in document.units]
    while stack:
        unit = stack.pop()
        yield unit
        stack.extend(unit.children)


def section_role(unit: Unit) -> str | None:
    """The canonical section role ("book"/"chapter"/"verse") a unit plays.

    Reads the unit's own `type` first, then a TEI-style ``type`` attribute
    (``<div type="chapter">``; ``surah`` counts as a chapter), then treats a
    level-1 markdown heading (the PDF route, issue #175) as a chapter.
    `None` for anything that isn't section-shaped.
    """
    unit_type = unit.type.lower()
    attr_type = unit.attrs.get("type", "").lower()
    for role in ("verse", "chapter", "book"):
        if unit_type == role or attr_type == role:
            return role
    if attr_type in _CHAPTER_ATTR_TYPES:
        return "chapter"
    if unit_type == "section" and unit.attrs.get("level") == "1":
        return "chapter"
    return None


def _detect(roles: Counter[str]) -> CorpusCategory:
    """``religious`` needs both verses and chapters (a bible chapter without
    verses is just a book chapter); ``book`` needs at least two chapters
    (one lone chapter wrapper is indistinguishable from a plain document)
    or explicit book divisions; everything else is a ``document``."""
    if roles["verse"] and roles["chapter"]:
        return CorpusCategory.RELIGIOUS
    if roles["chapter"] >= 2 or roles["book"]:
        return CorpusCategory.BOOK
    return CorpusCategory.DOCUMENT


def detect_category(documents: list[Document]) -> CorpusCategory:
    """Classify parsed documents by the section roles their units carry."""
    return _detect(_count_roles(documents))


def _count_roles(documents: Iterable[Document]) -> Counter[str]:
    return Counter(
        role for unit in _iter_units(documents) if (role := section_role(unit))
    )


def _spec_for(
    category: CorpusCategory, root_type: str, roles: Counter[str]
) -> SectionSpec:
    """The TF section levels a category declares, limited to roles that
    actually occur — an empty declared level breaks the walk."""
    if category is CorpusCategory.RELIGIOUS:
        levels = tuple(r for r in ("book", "chapter", "verse") if roles[r])
    elif category is CorpusCategory.BOOK:
        levels = ("chapter",) if roles["chapter"] else ("book",)
    else:
        levels = ()
    return SectionSpec(
        types=(root_type, *levels),
        features=("title", *("label",) * len(levels)),
    )


def promote_sections(base: TypeMapper, spec: SectionSpec) -> TypeMapper:
    """Wrap a converter's `otype_for` so section-role units land on the
    canonical section otypes the spec declares (`book`/`chapter`/`verse`),
    leaving everything else to the converter's own vocabulary."""

    declared = frozenset(spec.types)

    def otype_for(unit: Unit) -> str:
        role = section_role(unit)
        if role is not None and role in declared:
            return role
        return base(unit)

    return otype_for


def categorize(
    documents: list[Document],
    requested: CorpusCategory | None,
    *,
    root_type: str,
    base_otype_for: TypeMapper,
    max_category: CorpusCategory = CorpusCategory.RELIGIOUS,
) -> tuple[CorpusCategory, SectionSpec, TypeMapper, list[str]]:
    """Resolve one conversion's category, section spec, and type mapper.

    A `requested` override is honored when it asks for *at most* the
    structure the source actually has (flattening a bible to ``book`` or
    ``document`` is always expressible); asking for more downgrades to the
    detected category with a warning. `max_category` is the converter's own
    ceiling — a format whose vocabulary can't express verse divisions caps
    at ``book`` no matter what detection or the client says.
    """
    roles = _count_roles(documents)
    detected = _detect(roles)
    if _RANK[detected] > _RANK[max_category]:
        detected = max_category
    warnings: list[str] = []
    if requested is None or _RANK[requested] <= _RANK[detected]:
        effective = requested or detected
    else:
        effective = detected
        warnings.append(
            f"Requested category '{requested.value}' needs structure the "
            f"source does not carry; using '{detected.value}' instead."
        )
    spec = _spec_for(effective, root_type, roles)
    return effective, spec, promote_sections(base_otype_for, spec), warnings
