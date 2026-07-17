"""Docling → Context Fabric v1 canonical content graph.

Parses an uploaded document (PDF, DOCX, PPTX, XLSX, HTML, Markdown, images
with OCR, …) with `Docling <https://www.docling.ai>`_ and extracts it into
the canonical entities defined by the v1 JSON Schemas under
`packages/common/src/common/schemas/context_fabric/v1/` (see
`docs/architecture/context-fabric/`): one Work + Edition + SourceAsset and an
ordered ContentNode tree whose text lives exclusively in TextFragments, with
Docling's page/bbox provenance mapped onto embedded PhysicalLocators.

This module deliberately does NOT reduce to the `Document`/`Unit` parser
schema (`admin.parsers.schema`) — that shape has no place for physical
locators, per-fragment confidence, or namespaced types, which are exactly
what Docling's layout analysis provides and what the canonical graph exists
to preserve. It is the first producer of the phase-2 "canonical emission"
output described in `docs/architecture/context-fabric/07-migration-mapping.md`.

Split of responsibilities:

- `extract_graph(doc, ...)` maps an in-memory `DoclingDocument` (the
  lightweight `docling-core` data model, a regular dependency) to a
  `CanonicalGraph`. Fully testable without the heavy `docling` converter.
- `parse_file(path, ...)` runs the actual Docling `DocumentConverter`
  (layout models, OCR, table structure) and feeds the result to
  `extract_graph`. Requires the `corpora-admin[docling]` extra; raises
  `DoclingNotInstalledError` otherwise.

Mapping decisions (the "docling" profile in
`docs/architecture/context-fabric/02-node-taxonomy.md` §5):

- Docling's body tree is mostly flat: section headers are siblings of the
  text that follows them. Headers are **folded** into nesting
  `generic:section` container nodes by their `level`, so the graph gets a
  real navigable hierarchy; the header's own text survives as a child
  `generic:heading` node (keeping its fragments + locators), never as bare
  `heading` metadata.
- Pages are physical accident, not structure: no `phys:page` nodes are
  created. Page position lands on each node/fragment as
  `PhysicalLocator.pageIndex`/`bbox` (bbox normalized to top-left origin,
  unit `pt`), per `docs/architecture/context-fabric/01-domain-model.md` §4.
- An item whose provenance spans several regions/pages with valid charspans
  becomes one TextFragment per region, each with its own locator — the
  schema's page-break rule. Otherwise the item is a single fragment carrying
  every locator.
- Tables keep their grid as child `generic:table-row` → `generic:table-cell`
  nodes (cell text stays searchable); captions of tables/pictures become
  child `generic:caption` nodes. Furniture (page headers/footers) is skipped
  unless `include_furniture=True`.
- Everything Docling-specific (raw label, self_ref, list markers, heading
  levels, …) survives losslessly in `ext["src/docling"]`.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from docling_core.types.doc import DocItemLabel, DoclingDocument, GroupLabel
from docling_core.types.doc.base import CoordOrigin
from docling_core.types.doc.document import (
    ContentLayer,
    FloatingItem,
    GroupItem,
    ListItem,
    NodeItem,
    PictureItem,
    ProvenanceItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)

from ._ids import uuid7
from .validation import validate_graph

SCHEMA_VERSION = "1.0.0"
_PROFILE = "docling"
_EXT_NS = "src/docling"

# DocItemLabel → (category, type). Raw labels always survive in ext, so
# lossy-looking collapses here (handwritten text → paragraph) lose nothing.
_TEXT_LABEL_MAP: dict[DocItemLabel, tuple[str, str]] = {
    DocItemLabel.TITLE: ("heading", "generic:title"),
    DocItemLabel.SECTION_HEADER: ("heading", "generic:heading"),
    DocItemLabel.TEXT: ("block", "generic:paragraph"),
    DocItemLabel.PARAGRAPH: ("block", "generic:paragraph"),
    DocItemLabel.HANDWRITTEN_TEXT: ("block", "generic:paragraph"),
    DocItemLabel.LIST_ITEM: ("block", "generic:list-item"),
    DocItemLabel.CAPTION: ("block", "generic:caption"),
    DocItemLabel.FOOTNOTE: ("note", "generic:footnote"),
    DocItemLabel.CODE: ("block", "generic:code"),
    DocItemLabel.FORMULA: ("block", "generic:formula"),
    DocItemLabel.REFERENCE: ("block", "generic:reference"),
    DocItemLabel.PAGE_HEADER: ("note", "generic:page-header"),
    DocItemLabel.PAGE_FOOTER: ("note", "generic:page-footer"),
    DocItemLabel.CHECKBOX_SELECTED: ("block", "generic:checkbox"),
    DocItemLabel.CHECKBOX_UNSELECTED: ("block", "generic:checkbox"),
}
_TEXT_LABEL_FALLBACK = ("block", "generic:element")

_GROUP_LABEL_MAP: dict[GroupLabel, tuple[str, str]] = {
    GroupLabel.LIST: ("list", "generic:list"),
    GroupLabel.ORDERED_LIST: ("list", "generic:list"),
    GroupLabel.INLINE: ("inline", "generic:inline"),
    GroupLabel.CHAPTER: ("division", "generic:chapter"),
    GroupLabel.SECTION: ("section", "generic:section"),
    GroupLabel.SHEET: ("division", "generic:sheet"),
    GroupLabel.SLIDE: ("division", "generic:slide"),
    GroupLabel.COMMENT_SECTION: ("note", "generic:comment"),
    GroupLabel.PICTURE_AREA: ("figure", "generic:figure"),
}
_GROUP_LABEL_FALLBACK = ("division", "generic:group")

# Node types promoted to ordinal-addressed reference levels (outermost
# first). Only the types actually present in a parse enter the edition's
# structureProfile — see `_assign_reference_levels`.
_REF_LEVEL_TYPES = (
    "generic:sheet",
    "generic:slide",
    "generic:chapter",
    "generic:section",
    "generic:paragraph",
)

_MIMETYPE_TO_SOURCE_FORMAT = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/epub+zip": "epub",
    "text/plain": "plain",
    "application/xml": "xml",
    "text/xml": "xml",
}

_SUFFIX_TO_SOURCE_FORMAT = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".epub": "epub",
    ".txt": "plain",
    ".xml": "xml",
}

_LANG_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


class DoclingNotInstalledError(RuntimeError):
    """The heavy `docling` converter is not installed (only `docling-core` is)."""


@dataclass
class CanonicalGraph:
    """One parsed document as Context Fabric v1 entities (plain JSON dicts)."""

    corpus: dict[str, Any] | None
    work: dict[str, Any]
    edition: dict[str, Any]
    source_asset: dict[str, Any]
    nodes: list[dict[str, Any]]
    fragments: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """The `graph.json` shape: every entity of one conversion, together."""
        graph: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION}
        if self.corpus is not None:
            graph["corpus"] = self.corpus
        graph.update(
            work=self.work,
            edition=self.edition,
            sourceAsset=self.source_asset,
            nodes=self.nodes,
            fragments=self.fragments,
        )
        return graph

    def validate(self) -> None:
        validate_graph(self.to_dict())


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:128].rstrip("-") or "document"


def _source_format(mimetype: str | None, filename: str | None) -> str:
    if mimetype:
        if mimetype in _MIMETYPE_TO_SOURCE_FORMAT:
            return _MIMETYPE_TO_SOURCE_FORMAT[mimetype]
        prefix = mimetype.split("/", 1)[0]
        if prefix in ("image", "audio", "video"):
            return prefix
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _SUFFIX_TO_SOURCE_FORMAT:
            return _SUFFIX_TO_SOURCE_FORMAT[suffix]
    return "other"


def _parser_version() -> str:
    try:
        return metadata.version("corpora-admin")
    except metadata.PackageNotFoundError:
        return "0.0.0"


class _GraphBuilder:
    def __init__(
        self,
        doc: DoclingDocument,
        *,
        source_path: Path | None,
        language: str,
        corpus_id: str | None,
        title: str | None,
        include_furniture: bool,
    ) -> None:
        self.doc = doc
        self.source_path = source_path
        self.language = language
        self.given_corpus_id = corpus_id
        self.given_title = title
        self.nodes: list[dict[str, Any]] = []
        self.fragments: list[dict[str, Any]] = []
        self.edition_id = uuid7()
        self.asset_id = uuid7()
        # next sibling ordinal per parent node id ("" = the root's slot)
        self._ordinals: dict[str, int] = {}
        # items already emitted out of walk order (e.g. captions), by self_ref
        self._consumed: set[str] = set()
        self._layers = {ContentLayer.BODY}
        if include_furniture:
            self._layers.add(ContentLayer.FURNITURE)
        self._title_from_doc: str | None = None

    # ── node / fragment factories ─────────────────────────────────────────

    def _new_node(
        self,
        parent: dict[str, Any] | None,
        category: str,
        type_: str,
        *,
        label: str | None = None,
        source_local_id: str | None = None,
        locators: list[dict[str, Any]] | None = None,
        ext_src: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parent_key = parent["id"] if parent else ""
        ordinal = self._ordinals.get(parent_key, 0)
        self._ordinals[parent_key] = ordinal + 1
        node: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "id": uuid7(),
            "editionId": self.edition_id,
            "parentId": parent["id"] if parent else None,
            "ordinal": ordinal,
            "depth": parent["depth"] + 1 if parent else 0,
            "category": category,
            "type": type_,
        }
        if label:
            node["label"] = label
        if source_local_id:
            node["sourceLocalId"] = source_local_id
        if locators:
            node["locators"] = locators
        if ext_src:
            node["ext"] = {_EXT_NS: ext_src}
        self.nodes.append(node)
        return node

    def _new_fragment(
        self,
        node: dict[str, Any],
        text: str,
        *,
        after: str = "",
        char_start: int,
        char_end: int,
        locators: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ordinal = self._ordinals.get(f"frag:{node['id']}", 0)
        self._ordinals[f"frag:{node['id']}"] = ordinal + 1
        fragment: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "id": uuid7(),
            "nodeId": node["id"],
            "ordinal": ordinal,
            "text": text,
            "charStart": char_start,
            "charEnd": char_end,
        }
        if after:
            fragment["after"] = after
        if locators:
            fragment["locators"] = locators
        self.fragments.append(fragment)
        return fragment

    # ── physical locators ─────────────────────────────────────────────────

    def _locator(self, prov: ProvenanceItem) -> dict[str, Any]:
        locator: dict[str, Any] = {
            "sourceAssetId": self.asset_id,
            # Docling page_no is 1-based; PhysicalLocator.pageIndex is the
            # 0-based physical page index.
            "pageIndex": max(prov.page_no - 1, 0),
        }
        bbox: Any = prov.bbox
        if bbox is not None:
            if bbox.coord_origin == CoordOrigin.BOTTOMLEFT:
                page = self.doc.pages.get(prov.page_no)
                if page is not None and page.size is not None:
                    bbox = bbox.to_top_left_origin(page_height=page.size.height)
                else:
                    bbox = None  # can't normalize without the page height
            if bbox is not None:
                locator["bbox"] = {
                    "x": min(bbox.l, bbox.r),
                    "y": min(bbox.t, bbox.b),
                    "width": abs(bbox.r - bbox.l),
                    "height": abs(bbox.b - bbox.t),
                    "unit": "pt",
                }
        return locator

    def _locators(self, item: Any) -> list[dict[str, Any]]:
        prov = getattr(item, "prov", None) or []
        return [self._locator(p) for p in prov]

    # ── tree walk ─────────────────────────────────────────────────────────

    def _included(self, item: NodeItem) -> bool:
        layer = getattr(item, "content_layer", ContentLayer.BODY)
        return layer in self._layers

    def _emit_children(self, refs: list[Any], container: dict[str, Any]) -> None:
        """Emit `refs` under `container`, folding section headers into
        nesting `generic:section` nodes by their Docling heading level."""
        stack: list[tuple[int, dict[str, Any]]] = [(0, container)]
        for ref in refs:
            item = ref.resolve(self.doc)
            if item is None or item.self_ref in self._consumed or not self._included(item):
                continue
            if isinstance(item, SectionHeaderItem):
                level = item.level
                while len(stack) > 1 and stack[-1][0] >= level:
                    stack.pop()
                section = self._new_node(
                    stack[-1][1],
                    "section",
                    "generic:section",
                    label=item.text or None,
                    ext_src={"synthesized-from": item.self_ref, "level": level},
                )
                self._emit_text_item(item, section)
                stack.append((level, section))
            else:
                self._emit_item(item, stack[-1][1])

    def _emit_item(self, item: NodeItem, parent: dict[str, Any]) -> None:
        self._consumed.add(item.self_ref)
        if isinstance(item, GroupItem):
            self._emit_group(item, parent)
        elif isinstance(item, TableItem):
            self._emit_table(item, parent)
        elif isinstance(item, PictureItem):
            self._emit_picture(item, parent)
        elif isinstance(item, TextItem):
            self._emit_text_item(item, parent)
        else:
            # Unknown/rare node kinds (key-value regions, form items, …):
            # keep the position in the tree, park the payload in ext.
            node = self._new_node(
                parent,
                "block",
                "generic:element",
                source_local_id=item.self_ref,
                locators=self._locators(item) or None,
                ext_src={"label": str(getattr(item, "label", type(item).__name__))},
            )
            self._emit_children(item.children, node)

    def _emit_group(self, group: GroupItem, parent: dict[str, Any]) -> None:
        category, type_ = _GROUP_LABEL_MAP.get(group.label, _GROUP_LABEL_FALLBACK)
        ext: dict[str, Any] = {"label": group.label.value}
        if group.name and group.name != "group":
            ext["name"] = group.name
        if group.label == GroupLabel.ORDERED_LIST:
            ext["ordered"] = True
        node = self._new_node(
            parent, category, type_, source_local_id=group.self_ref, ext_src=ext
        )
        self._emit_children(group.children, node)

    def _emit_text_item(
        self,
        item: TextItem,
        parent: dict[str, Any],
        *,
        category: str | None = None,
        type_: str | None = None,
    ) -> dict[str, Any]:
        self._consumed.add(item.self_ref)
        if category is None or type_ is None:
            category, type_ = _TEXT_LABEL_MAP.get(item.label, _TEXT_LABEL_FALLBACK)
        ext: dict[str, Any] = {"label": item.label.value}
        if isinstance(item, ListItem):
            if item.marker:
                ext["marker"] = item.marker
            if item.enumerated:
                ext["enumerated"] = True
        if isinstance(item, SectionHeaderItem):
            ext["level"] = item.level
        code_language = getattr(item, "code_language", None)
        if code_language:
            ext["code-language"] = str(code_language)
        if isinstance(item, TitleItem) and self._title_from_doc is None and item.text:
            self._title_from_doc = item.text
        node = self._new_node(
            parent, category, type_, source_local_id=item.self_ref, ext_src=ext
        )
        self._add_fragments(node, item)
        if item.children:
            self._emit_children(item.children, node)
        return node

    def _emit_captions(self, item: FloatingItem, node: dict[str, Any]) -> None:
        for caption_ref in item.captions:
            caption = caption_ref.resolve(self.doc)
            if caption is None or caption.self_ref in self._consumed:
                continue
            self._emit_text_item(caption, node, category="block", type_="generic:caption")

    def _emit_table(self, table: TableItem, parent: dict[str, Any]) -> None:
        is_index = table.label == DocItemLabel.DOCUMENT_INDEX
        data = table.data
        node = self._new_node(
            parent,
            "table",
            "generic:index" if is_index else "generic:table",
            source_local_id=table.self_ref,
            locators=self._locators(table) or None,
            ext_src={
                "label": table.label.value,
                "num-rows": data.num_rows if data else 0,
                "num-cols": data.num_cols if data else 0,
            },
        )
        self._emit_captions(table, node)
        if data and data.table_cells:
            rows: dict[int, list[Any]] = {}
            for cell in data.table_cells:
                rows.setdefault(cell.start_row_offset_idx, []).append(cell)
            for row_index in sorted(rows):
                row_node = self._new_node(
                    node, "block", "generic:table-row", ext_src={"row": row_index}
                )
                for cell in sorted(rows[row_index], key=lambda c: c.start_col_offset_idx):
                    cell_ext: dict[str, Any] = {
                        "row": cell.start_row_offset_idx,
                        "col": cell.start_col_offset_idx,
                    }
                    if cell.row_span > 1:
                        cell_ext["row-span"] = cell.row_span
                    if cell.col_span > 1:
                        cell_ext["col-span"] = cell.col_span
                    if cell.column_header:
                        cell_ext["column-header"] = True
                    if cell.row_header:
                        cell_ext["row-header"] = True
                    cell_node = self._new_node(
                        row_node, "block", "generic:table-cell", ext_src=cell_ext
                    )
                    if cell.text:
                        self._new_fragment(
                            cell_node,
                            cell.text,
                            char_start=0,
                            char_end=len(cell.text),
                        )
        self._emit_children(table.children, node)

    def _emit_picture(self, picture: PictureItem, parent: dict[str, Any]) -> None:
        is_chart = picture.label == DocItemLabel.CHART
        node = self._new_node(
            parent,
            "figure",
            "generic:chart" if is_chart else "generic:figure",
            source_local_id=picture.self_ref,
            locators=self._locators(picture) or None,
            ext_src={"label": picture.label.value},
        )
        self._emit_captions(picture, node)
        self._emit_children(picture.children, node)

    # ── fragments from text + provenance ──────────────────────────────────

    def _add_fragments(self, node: dict[str, Any], item: TextItem) -> None:
        text = item.text or ""
        prov = sorted(
            item.prov,
            key=lambda p: (p.page_no, p.charspan[0] if p.charspan else 0),
        )
        if not text:
            if prov:
                node["locators"] = [self._locator(p) for p in prov]
            return
        spans = [tuple(p.charspan) for p in prov if p.charspan is not None]
        splittable = (
            len(prov) > 1
            and len(spans) == len(prov)
            and all(0 <= start < end <= len(text) for start, end in spans)
            and all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))
        )
        if not splittable:
            self._new_fragment(
                node,
                text,
                char_start=0,
                char_end=len(text),
                locators=[self._locator(p) for p in prov] or None,
            )
            return
        # One fragment per provenance region (page break / column break in
        # the middle of a logical item); the text between two regions'
        # charspans becomes the leading fragment's `after` separator.
        for i, (prov_item, (start, end)) in enumerate(zip(prov, spans, strict=True)):
            if i == 0:
                start = 0  # any preamble outside the first span still belongs to it
            next_start = spans[i + 1][0] if i + 1 < len(spans) else len(text)
            self._new_fragment(
                node,
                text[start:end],
                after=text[end:next_start],
                char_start=start,
                char_end=end,
                locators=[self._locator(prov_item)],
            )

    # ── reference levels ──────────────────────────────────────────────────

    def _assign_reference_levels(self) -> list[dict[str, Any]]:
        """Set 1-based `refOrdinal` per (parent, type) on level-type nodes and
        return the structureProfile levels actually present, outermost first."""
        present: dict[str, bool] = {}
        counters: dict[tuple[str | None, str], int] = {}
        for node in self.nodes:  # document order by construction
            type_ = node["type"]
            if type_ not in _REF_LEVEL_TYPES:
                continue
            key = (node["parentId"], type_)
            counters[key] = counters.get(key, 0) + 1
            node["refOrdinal"] = counters[key]
            present[type_] = True
        return [
            {"levelType": type_, "addressedBy": "ordinal"}
            for type_ in _REF_LEVEL_TYPES
            if type_ in present
        ]

    # ── entity assembly ───────────────────────────────────────────────────

    def build(self) -> CanonicalGraph:
        root = self._new_node(
            None,
            "root",
            "generic:document",
            source_local_id=self.doc.body.self_ref,
        )
        self._emit_children(self.doc.body.children, root)

        # childCount from the ordinal counters (a parent's next ordinal IS
        # its child count once the walk is complete)
        for node in self.nodes:
            node["childCount"] = self._ordinals.get(node["id"], 0)

        levels = self._assign_reference_levels()

        title = (
            self.given_title
            or self._title_from_doc
            or (self.doc.name if self.doc.name and self.doc.name != "file" else None)
            or (self.source_path.stem if self.source_path else None)
            or "Untitled"
        )
        root["label"] = title
        slug = _slugify(title)

        corpus: dict[str, Any] | None = None
        corpus_id = self.given_corpus_id
        if corpus_id is None:
            corpus_id = uuid7()
            corpus = {
                "schemaVersion": SCHEMA_VERSION,
                "id": corpus_id,
                "slug": slug,
                "title": title,
            }
            if self.language != "und":
                corpus["languages"] = [self.language]

        work_id = uuid7()
        work: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "id": work_id,
            "corpusId": corpus_id,
            "slug": slug,
            "title": title,
        }

        origin = self.doc.origin
        filename = (
            (origin.filename if origin is not None else None)
            or (self.source_path.name if self.source_path else None)
        )
        source_asset: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "id": self.asset_id,
            "editionId": self.edition_id,
            "sourceFormat": _source_format(
                origin.mimetype if origin is not None else None, filename
            ),
        }
        if origin is not None and origin.mimetype:
            source_asset["mediaType"] = origin.mimetype
        if filename:
            source_asset["filename"] = filename
        if self.source_path is not None and self.source_path.is_file():
            payload = self.source_path.read_bytes()
            source_asset["sha256"] = hashlib.sha256(payload).hexdigest()
            source_asset["byteSize"] = len(payload)
        if self.doc.pages:
            source_asset["pageCount"] = len(self.doc.pages)

        ext_src: dict[str, Any] = {"docling-core": _dep_version("docling-core")}
        docling_version = _dep_version("docling")
        if docling_version:
            ext_src["docling"] = docling_version

        edition: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "id": self.edition_id,
            "workId": work_id,
            "slug": slug,
            "title": title,
            "language": self.language,
            "version": "1.0.0",
            "sourceAssetIds": [self.asset_id],
            "provenance": {
                "parser": {
                    "name": "corpora-admin",
                    "version": _parser_version(),
                    "profile": _PROFILE,
                },
                "convertedAt": datetime.now(UTC).isoformat(),
                "sourceAssetId": self.asset_id,
            },
            "ext": {_EXT_NS: ext_src},
        }
        if levels:
            edition["refScheme"] = "monograph"
            edition["structureProfile"] = {"levels": levels}

        return CanonicalGraph(
            corpus=corpus,
            work=work,
            edition=edition,
            source_asset=source_asset,
            nodes=self.nodes,
            fragments=self.fragments,
        )


def _dep_version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def extract_graph(
    doc: DoclingDocument,
    *,
    source_path: Path | None = None,
    language: str = "und",
    corpus_id: str | None = None,
    title: str | None = None,
    include_furniture: bool = False,
    validate: bool = True,
) -> CanonicalGraph:
    """Map an in-memory `DoclingDocument` to a Context Fabric v1 graph.

    `language` is a BCP 47 tag for the edition (`"und"` = undetermined —
    Docling does not detect language). `corpus_id` attaches the Work to an
    existing Corpus instead of minting a single-document one. `title`
    overrides the title detected from the document. With `validate=True`
    (the default, per the phase-2 rule that converters validate their own
    output) the emitted graph is checked against the shipped schemas and a
    `GraphValidationError` raised on any violation.
    """
    if not _LANG_TAG_RE.match(language):
        raise ValueError(f"not a BCP 47 language tag: {language!r}")
    graph = _GraphBuilder(
        doc,
        source_path=source_path,
        language=language,
        corpus_id=corpus_id,
        title=title,
        include_furniture=include_furniture,
    ).build()
    if validate:
        graph.validate()
    return graph


# Docling's DocumentConverter loads layout/table models on first use and is
# not documented as safe for concurrent convert() calls — one shared
# instance behind a lock keeps the model cache warm across JobManager
# worker threads without racing them.
_converter: Any = None
_converter_lock = threading.Lock()


def _convert_with_docling(source: Path) -> DoclingDocument:
    global _converter
    with _converter_lock:
        if _converter is None:
            from docling.document_converter import DocumentConverter

            _converter = DocumentConverter()
        result = _converter.convert(str(source))
    return result.document


def parse_file(
    source: str | Path,
    *,
    language: str = "und",
    corpus_id: str | None = None,
    title: str | None = None,
    include_furniture: bool = False,
    validate: bool = True,
) -> CanonicalGraph:
    """Parse a document file with Docling and extract the canonical graph.

    Requires the heavy `docling` converter (`corpora-admin[docling]` extra);
    the mapping itself only needs `docling-core`. Raises
    `DoclingNotInstalledError` when the extra is missing.
    """
    if find_spec("docling") is None:
        raise DoclingNotInstalledError(
            "The Docling converter is not installed. Install the extra: "
            "`pip install corpora-admin[docling]` (or `uv sync --extra docling`)."
        )
    source = Path(source)
    doc = _convert_with_docling(source)
    return extract_graph(
        doc,
        source_path=source,
        language=language,
        corpus_id=corpus_id,
        title=title,
        include_furniture=include_furniture,
        validate=validate,
    )
