"""admin.ingest.docling_graph: DoclingDocument → Context Fabric v1 graph.

Documents are built in memory with `docling-core` (the exact data model the
heavy Docling converter produces), so the whole mapping is exercised without
layout models or OCR. Every graph these tests build passes `validate=True`,
i.e. is checked against the shipped v1 JSON Schemas on the way out.
"""

import hashlib
import uuid
from importlib.util import find_spec

import pytest
from admin.ingest import (
    CanonicalGraph,
    DoclingNotInstalledError,
    GraphValidationError,
    extract_graph,
    parse_file,
    validate_graph,
)
from admin.ingest._ids import uuid7
from docling_core.types.doc import DocItemLabel, DoclingDocument
from docling_core.types.doc.base import BoundingBox, CoordOrigin, Size
from docling_core.types.doc.document import (
    ContentLayer,
    DocumentOrigin,
    ProvenanceItem,
    TableCell,
    TableData,
)

# ── helpers ───────────────────────────────────────────────────────────────


def _index(graph: CanonicalGraph):
    by_id = {node["id"]: node for node in graph.nodes}

    def children_of(node):
        return sorted(
            (n for n in graph.nodes if n["parentId"] == node["id"]),
            key=lambda n: n["ordinal"],
        )

    def fragments_of(node):
        return sorted(
            (f for f in graph.fragments if f["nodeId"] == node["id"]),
            key=lambda f: f["ordinal"],
        )

    def text_of(node):
        return "".join(f["text"] + f.get("after", "") for f in fragments_of(node))

    return by_id, children_of, fragments_of, text_of


def _root(graph: CanonicalGraph):
    roots = [n for n in graph.nodes if n["parentId"] is None]
    assert len(roots) == 1, "an edition has exactly one root node"
    return roots[0]


# ── ids ───────────────────────────────────────────────────────────────────


def test_uuid7_is_version_7_and_unique():
    ids = [uuid7() for _ in range(100)]
    assert len(set(ids)) == 100
    for value in ids:
        assert uuid.UUID(value).version == 7


# ── basic structure and section folding ──────────────────────────────────


@pytest.fixture
def article_graph():
    doc = DoclingDocument(name="sample")
    doc.add_title(text="A Study of Things")
    doc.add_heading(text="Introduction", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="First paragraph.")
    doc.add_heading(text="Details", level=2)
    doc.add_text(label=DocItemLabel.TEXT, text="Nested paragraph.")
    doc.add_heading(text="Conclusion", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="Last paragraph.")
    return extract_graph(doc)


def test_root_node_shape(article_graph):
    root = _root(article_graph)
    assert root["category"] == "root"
    assert root["type"] == "generic:document"
    assert root["depth"] == 0
    assert root["ordinal"] == 0
    assert root["label"] == "A Study of Things"


def test_section_headers_fold_into_nested_sections(article_graph):
    _, children_of, _, text_of = _index(article_graph)
    root = _root(article_graph)
    top = children_of(root)
    assert [n["type"] for n in top] == [
        "generic:title",
        "generic:section",
        "generic:section",
    ]
    intro, conclusion = top[1], top[2]
    assert intro["label"] == "Introduction"
    assert conclusion["label"] == "Conclusion"

    intro_children = children_of(intro)
    # heading node, paragraph, then the folded level-2 subsection
    assert [n["type"] for n in intro_children] == [
        "generic:heading",
        "generic:paragraph",
        "generic:section",
    ]
    assert text_of(intro_children[0]) == "Introduction"
    assert text_of(intro_children[1]) == "First paragraph."

    details = intro_children[2]
    assert details["depth"] == intro["depth"] + 1
    assert [text_of(n) for n in children_of(details)] == [
        "Details",
        "Nested paragraph.",
    ]

    # conclusion pops back to level 1 (sibling of introduction)
    assert conclusion["parentId"] == root["id"]
    assert [text_of(n) for n in children_of(conclusion)] == [
        "Conclusion",
        "Last paragraph.",
    ]


def test_child_counts_and_ordinals(article_graph):
    _, children_of, _, _ = _index(article_graph)
    for node in article_graph.nodes:
        kids = children_of(node)
        assert node["childCount"] == len(kids)
        assert [k["ordinal"] for k in kids] == list(range(len(kids)))
        for kid in kids:
            assert kid["depth"] == node["depth"] + 1


def test_reference_levels_and_structure_profile(article_graph):
    edition = article_graph.edition
    assert edition["refScheme"] == "monograph"
    assert [level["levelType"] for level in edition["structureProfile"]["levels"]] == [
        "generic:section",
        "generic:paragraph",
    ]
    sections = [n for n in article_graph.nodes if n["type"] == "generic:section"]
    # two top-level sections number 1..2; the nested one restarts at 1
    assert [s["refOrdinal"] for s in sections] == [1, 1, 2]


def test_work_edition_corpus_metadata(article_graph):
    assert article_graph.work["title"] == "A Study of Things"
    assert article_graph.work["slug"] == "a-study-of-things"
    assert article_graph.corpus is not None
    assert article_graph.work["corpusId"] == article_graph.corpus["id"]
    edition = article_graph.edition
    assert edition["workId"] == article_graph.work["id"]
    assert edition["language"] == "und"
    assert edition["provenance"]["parser"]["profile"] == "docling"
    assert edition["sourceAssetIds"] == [article_graph.source_asset["id"]]
    assert article_graph.source_asset["editionId"] == edition["id"]


def test_existing_corpus_id_suppresses_corpus_entity():
    doc = DoclingDocument(name="joined")
    doc.add_text(label=DocItemLabel.TEXT, text="content")
    corpus_id = str(uuid.uuid4())
    graph = extract_graph(doc, corpus_id=corpus_id)
    assert graph.corpus is None
    assert graph.work["corpusId"] == corpus_id


def test_empty_document_is_root_only_and_valid():
    graph = extract_graph(DoclingDocument(name="empty"))
    assert len(graph.nodes) == 1
    assert graph.fragments == []
    assert "structureProfile" not in graph.edition


def test_invalid_language_rejected():
    with pytest.raises(ValueError, match="BCP 47"):
        extract_graph(DoclingDocument(name="x"), language="not a lang tag!")


# ── physical locators ─────────────────────────────────────────────────────


def test_bottomleft_bbox_normalized_to_top_left_points():
    doc = DoclingDocument(name="paged")
    doc.add_page(page_no=1, size=Size(width=612, height=792))
    prov = ProvenanceItem(
        page_no=1,
        bbox=BoundingBox(l=72, t=700, r=540, b=680, coord_origin=CoordOrigin.BOTTOMLEFT),
        charspan=(0, 5),
    )
    doc.add_text(label=DocItemLabel.TEXT, text="Hello", prov=prov)
    graph = extract_graph(doc)
    (fragment,) = graph.fragments
    (locator,) = fragment["locators"]
    assert locator["sourceAssetId"] == graph.source_asset["id"]
    assert locator["pageIndex"] == 0  # docling page_no is 1-based
    assert locator["bbox"] == {
        "x": 72,
        "y": 92,  # 792 - 700
        "width": 468,
        "height": 20,
        "unit": "pt",
    }
    assert graph.source_asset["pageCount"] == 1


def test_multi_region_item_splits_into_fragment_per_locator():
    doc = DoclingDocument(name="split")
    text = "Alpha beta gamma delta"
    item = doc.add_text(
        label=DocItemLabel.TEXT,
        text=text,
        prov=ProvenanceItem(
            page_no=1,
            bbox=BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT),
            charspan=(0, 10),
        ),
    )
    item.prov.append(
        ProvenanceItem(
            page_no=2,
            bbox=BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT),
            charspan=(11, 22),
        )
    )
    graph = extract_graph(doc)
    first, second = sorted(graph.fragments, key=lambda f: f["ordinal"])
    assert (first["text"], first["after"]) == ("Alpha beta", " ")
    assert (first["charStart"], first["charEnd"]) == (0, 10)
    assert first["locators"][0]["pageIndex"] == 0
    assert second["text"] == "gamma delta"
    assert (second["charStart"], second["charEnd"]) == (11, 22)
    assert second["locators"][0]["pageIndex"] == 1
    # concatenation reconstructs the item text exactly
    assert first["text"] + first["after"] + second["text"] == text


def test_overlapping_charspans_fall_back_to_single_fragment():
    doc = DoclingDocument(name="overlap")
    bbox = BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT)
    item = doc.add_text(
        label=DocItemLabel.TEXT,
        text="ambiguous provenance",
        prov=ProvenanceItem(page_no=1, bbox=bbox, charspan=(0, 15)),
    )
    item.prov.append(ProvenanceItem(page_no=1, bbox=bbox, charspan=(10, 20)))
    graph = extract_graph(doc)
    (fragment,) = graph.fragments
    assert fragment["text"] == "ambiguous provenance"
    assert len(fragment["locators"]) == 2


# ── tables, figures, lists, furniture ─────────────────────────────────────


def _cell(text, row, col, **kwargs):
    return TableCell(
        text=text,
        start_row_offset_idx=row,
        end_row_offset_idx=row + kwargs.pop("row_span", 1),
        start_col_offset_idx=col,
        end_col_offset_idx=col + kwargs.pop("col_span", 1),
        **kwargs,
    )


def test_table_grid_becomes_rows_and_cells_with_caption():
    doc = DoclingDocument(name="tabular")
    data = TableData(
        num_rows=2,
        num_cols=2,
        table_cells=[
            _cell("Name", 0, 0, column_header=True),
            _cell("Age", 0, 1, column_header=True),
            _cell("Ada", 1, 0),
            _cell("36", 1, 1),
        ],
    )
    table = doc.add_table(data=data)
    caption = doc.add_text(label=DocItemLabel.CAPTION, text="Table 1: People", parent=table)
    table.captions.append(caption.get_ref())

    graph = extract_graph(doc)
    _, children_of, _, text_of = _index(graph)
    (table_node,) = (n for n in graph.nodes if n["category"] == "table")
    assert table_node["type"] == "generic:table"
    assert table_node["ext"]["src/docling"]["num-rows"] == 2

    table_children = children_of(table_node)
    assert [n["type"] for n in table_children] == [
        "generic:caption",
        "generic:table-row",
        "generic:table-row",
    ]
    assert text_of(table_children[0]) == "Table 1: People"
    header_cells = children_of(table_children[1])
    assert [text_of(c) for c in header_cells] == ["Name", "Age"]
    assert header_cells[0]["ext"]["src/docling"]["column-header"] is True
    assert [text_of(c) for c in children_of(table_children[2])] == ["Ada", "36"]
    # the caption was emitted exactly once despite also being a tree child
    assert sum(1 for n in graph.nodes if n["type"] == "generic:caption") == 1


def test_picture_with_caption_and_locator():
    doc = DoclingDocument(name="figures")
    doc.add_page(page_no=1, size=Size(width=100, height=100))
    picture = doc.add_picture(
        prov=ProvenanceItem(
            page_no=1,
            bbox=BoundingBox(l=10, t=90, r=60, b=40, coord_origin=CoordOrigin.BOTTOMLEFT),
            charspan=(0, 0),
        )
    )
    caption = doc.add_text(label=DocItemLabel.CAPTION, text="Figure 1", parent=picture)
    picture.captions.append(caption.get_ref())

    graph = extract_graph(doc)
    _, children_of, _, text_of = _index(graph)
    (figure,) = (n for n in graph.nodes if n["category"] == "figure")
    assert figure["type"] == "generic:figure"
    assert figure["locators"][0]["pageIndex"] == 0
    assert figure["locators"][0]["bbox"]["y"] == 10  # 100 - 90, top-left origin
    assert [text_of(n) for n in children_of(figure)] == ["Figure 1"]
    # figures carry no fragments of their own
    assert not [f for f in graph.fragments if f["nodeId"] == figure["id"]]


def test_list_group_and_items():
    doc = DoclingDocument(name="listy")
    group = doc.add_list_group()
    doc.add_list_item(text="one", parent=group, marker="-")
    doc.add_list_item(text="two", parent=group, marker="-")
    graph = extract_graph(doc)
    _, children_of, _, text_of = _index(graph)
    (list_node,) = (n for n in graph.nodes if n["category"] == "list")
    assert list_node["type"] == "generic:list"
    items = children_of(list_node)
    assert [n["type"] for n in items] == ["generic:list-item"] * 2
    assert [text_of(n) for n in items] == ["one", "two"]
    assert items[0]["ext"]["src/docling"]["marker"] == "-"


def test_furniture_skipped_by_default_included_on_request():
    doc = DoclingDocument(name="furnished")
    doc.add_text(
        label=DocItemLabel.PAGE_HEADER,
        text="Running Head",
        content_layer=ContentLayer.FURNITURE,
    )
    doc.add_text(label=DocItemLabel.TEXT, text="Body text.")

    graph = extract_graph(doc)
    assert not [n for n in graph.nodes if n["type"] == "generic:page-header"]

    graph = extract_graph(doc, include_furniture=True)
    (header,) = (n for n in graph.nodes if n["type"] == "generic:page-header")
    assert header["category"] == "note"


# ── source asset ──────────────────────────────────────────────────────────


def test_source_asset_facts_from_origin_and_file(tmp_path):
    payload = b"%PDF-1.7 fake"
    source = tmp_path / "study.pdf"
    source.write_bytes(payload)
    doc = DoclingDocument(name="study")
    doc.origin = DocumentOrigin(
        mimetype="application/pdf", binary_hash=1234, filename="study.pdf"
    )
    doc.add_text(label=DocItemLabel.TEXT, text="content")
    graph = extract_graph(doc, source_path=source)
    asset = graph.source_asset
    assert asset["sourceFormat"] == "pdf"
    assert asset["mediaType"] == "application/pdf"
    assert asset["filename"] == "study.pdf"
    assert asset["byteSize"] == len(payload)
    assert asset["sha256"] == hashlib.sha256(payload).hexdigest()


def test_unknown_mimetype_maps_to_other():
    doc = DoclingDocument(name="docx")
    doc.origin = DocumentOrigin(
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        binary_hash=1,
        filename="notes.docx",
    )
    graph = extract_graph(doc)
    assert graph.source_asset["sourceFormat"] == "other"


# ── validation ────────────────────────────────────────────────────────────


def test_validate_graph_reports_every_violation(article_graph):
    graph = article_graph.to_dict()
    graph["nodes"][0]["category"] = "not-a-category"
    del graph["fragments"][0]["text"]
    with pytest.raises(GraphValidationError) as excinfo:
        validate_graph(graph)
    message = str(excinfo.value)
    assert "nodes[0]" in message
    assert "fragments[0]" in message


# ── parse_file guard ──────────────────────────────────────────────────────


@pytest.mark.skipif(
    find_spec("docling") is not None, reason="docling extra is installed"
)
def test_parse_file_requires_docling_extra(tmp_path):
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.7")
    with pytest.raises(DoclingNotInstalledError, match=r"corpora-admin\[docling\]"):
        parse_file(source)
