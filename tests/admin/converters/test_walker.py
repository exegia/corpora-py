"""_walker: metadata flattening, unit features, and the walk itself (fake CV)."""

import pytest
from admin.converters._walker import (
    SectionSpec,
    _unit_features,
    _walk_unit,
    convert_documents,
    metadata_features,
    set_features,
)
from admin.parsers.schema import (
    Document,
    DocumentMetadata,
    SourceFormat,
    Token,
    Unit,
)


class FakeCV:
    """Records the walker's node/slot/feature/meta call sequence."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._node_counter = 0
        self._slot_counter = 0
        self.declared_meta: set[str] = set()

    def node(self, otype):
        self._node_counter += 1
        node = (otype, self._node_counter)
        self.calls.append(("node", otype))
        return node

    def slot(self):
        self._slot_counter += 1
        slot = ("word", self._slot_counter)
        self.calls.append(("slot", self._slot_counter))
        return slot

    def meta(self, name, **kwargs):
        self.declared_meta.add(name)
        self.calls.append(("meta", name, kwargs))

    def feature(self, node, **features):
        # Contract from packages/admin/CLAUDE.md: every feature must have
        # been declared via cv.meta() first or cv.walk() fails validation.
        for name in features:
            assert name in self.declared_meta, f"feature {name!r} set before cv.meta()"
        self.calls.append(("feature", node, features))

    def terminate(self, node):
        self.calls.append(("terminate", node))


class TestMetadataFeatures:
    def test_title_defaults_to_untitled(self):
        meta = DocumentMetadata(source_format=SourceFormat.PLAIN)
        features = metadata_features(meta)
        assert features["title"] == "Untitled"
        assert features["source_format"] == "plain"

    def test_lists_joined_with_semicolon(self):
        meta = DocumentMetadata(
            source_format=SourceFormat.EPUB,
            creators=["Alice", "Bob"],
            subjects=["history", "war"],
        )
        features = metadata_features(meta)
        assert features["creators"] == "Alice; Bob"
        assert features["subjects"] == "history; war"

    def test_unset_optionals_omitted(self):
        features = metadata_features(DocumentMetadata(source_format=SourceFormat.PDF))
        for absent in ("creators", "language", "publisher", "date", "description"):
            assert absent not in features

    def test_extra_merged_last_and_wins(self):
        meta = DocumentMetadata(
            source_format=SourceFormat.PDF,
            title="Real Title",
            extra={"title": "Extra Title", "producer": "pdflatex"},
        )
        features = metadata_features(meta)
        assert features["title"] == "Extra Title"
        assert features["producer"] == "pdflatex"


class TestUnitFeatures:
    def test_tag_label_uid(self):
        unit = Unit(type="div", id="d1", label="Chapter One")
        assert _unit_features(unit) == {"tag": "div", "label": "Chapter One", "uid": "d1"}

    def test_none_label_and_id_omitted(self):
        assert _unit_features(Unit(type="p")) == {"tag": "p"}

    def test_source_attrs_win_on_collision(self):
        unit = Unit(type="div", label="ours", attrs={"label": "theirs", "class": "x"})
        features = _unit_features(unit)
        assert features["label"] == "theirs"
        assert features["class"] == "x"


class TestSetFeatures:
    def test_declares_meta_before_setting(self):
        cv = FakeCV()
        node = cv.node("p")
        set_features(cv, node, tag="p", custom="v")
        assert {"tag", "custom"} <= cv.declared_meta
        # ordering: both metas precede the feature call
        kinds = [c[0] for c in cv.calls]
        assert kinds.index("feature") > kinds.index("meta")


class TestWalkUnit:
    def test_tokens_become_slots_with_text_after(self):
        cv = FakeCV()
        unit = Unit(type="p", tokens=[Token(text="Hi", after=" "), Token(text="there")])
        _walk_unit(cv, unit, lambda u: "paragraph")
        slot_features = [c for c in cv.calls if c[0] == "feature" and "text" in c[2]]
        assert [c[2] for c in slot_features] == [
            {"text": "Hi", "after": " "},
            {"text": "there", "after": ""},
        ]

    def test_empty_leaf_gets_placeholder_slot(self):
        # A node with zero slots is silently deleted by TF's unlinked-nodes
        # pass; the walker must emit one empty placeholder slot.
        cv = FakeCV()
        _walk_unit(cv, Unit(type="img", attrs={"src": "x.png"}), lambda u: "element")
        assert ("slot", 1) in cv.calls
        placeholder = [c for c in cv.calls if c[0] == "feature" and "text" in c[2]]
        assert placeholder[0][2] == {"text": "", "after": ""}

    def test_parent_with_children_gets_no_placeholder(self):
        cv = FakeCV()
        unit = Unit(type="div", children=[Unit(type="p", tokens=[Token(text="x")])])
        _walk_unit(cv, unit, lambda u: "element")
        assert cv._slot_counter == 1  # only the child's real token

    def test_nodes_terminated_in_child_first_order(self):
        cv = FakeCV()
        unit = Unit(type="div", children=[Unit(type="p", tokens=[Token(text="x")])])
        _walk_unit(cv, unit, lambda u: u.type)
        terminations = [c[1] for c in cv.calls if c[0] == "terminate"]
        assert terminations == [("p", 2), ("div", 1)]

    def test_otype_for_applied_per_unit(self):
        cv = FakeCV()
        unit = Unit(type="blockquote", tokens=[Token(text="q")])
        _walk_unit(cv, unit, lambda u: "paragraph" if u.type == "blockquote" else "element")
        assert ("node", "paragraph") in cv.calls


class TestSectionSpec:
    def test_length_mismatch_rejected(self):
        with pytest.raises(ValueError, match="one feature per section type"):
            SectionSpec(types=("book", "chapter"), features=("label",))

    def test_empty_spec_rejected(self):
        with pytest.raises(ValueError):
            SectionSpec(types=(), features=())

    def test_feature_for_maps_type_to_feature(self):
        spec = SectionSpec(types=("text", "chapter"), features=("title", "label"))
        assert spec.feature_for == {"text": "title", "chapter": "label"}


def _section_walk(unit, section_features):
    cv = FakeCV()
    _walk_unit(cv, unit, lambda u: u.type, section_features, {})
    return cv


def _node_features(cv, otype):
    """Features set on nodes (not slots) of the given otype, in walk order."""
    return [
        c[2]
        for c in cv.calls
        if c[0] == "feature" and isinstance(c[1], tuple) and c[1][0] == otype
    ]


class TestWalkUnitSections:
    def test_units_own_label_wins(self):
        unit = Unit(type="chapter", label="Genesis 1", tokens=[Token(text="x")])
        cv = _section_walk(unit, {"chapter": "label"})
        assert _node_features(cv, "chapter")[0]["label"] == "Genesis 1"

    def test_source_id_used_when_label_missing(self):
        unit = Unit(type="verse", id="GEN.1.1", tokens=[Token(text="x")])
        cv = _section_walk(unit, {"verse": "label"})
        assert _node_features(cv, "verse")[0]["label"] == "GEN.1.1"

    def test_ordinal_fallback_when_label_and_id_missing(self):
        parent = Unit(
            type="book",
            label="B",
            children=[
                Unit(type="chapter", tokens=[Token(text="x")]),
                Unit(type="chapter", tokens=[Token(text="y")]),
            ],
        )
        cv = _section_walk(parent, {"book": "label", "chapter": "label"})
        assert [f["label"] for f in _node_features(cv, "chapter")] == ["1", "2"]

    def test_ordinals_are_per_parent(self):
        # Chapters restart at 1 under each book — "Chapter 1" of book two,
        # not "Chapter 3" of the corpus.
        def book():
            return Unit(
                type="book",
                label="B",
                children=[
                    Unit(type="chapter", tokens=[Token(text="x")]),
                    Unit(type="chapter", tokens=[Token(text="y")]),
                ],
            )

        cv = FakeCV()
        counters: dict[str, int] = {}
        features = {"chapter": "label"}
        _walk_unit(cv, book(), lambda u: u.type, features, counters)
        _walk_unit(cv, book(), lambda u: u.type, features, counters)
        assert [f["label"] for f in _node_features(cv, "chapter")] == ["1", "2", "1", "2"]

    def test_existing_feature_value_not_overwritten(self):
        # A TEI div carrying its own n="3" as the section feature keeps it.
        unit = Unit(type="chapter", attrs={"label": "III"}, tokens=[Token(text="x")])
        cv = _section_walk(unit, {"chapter": "label"})
        assert _node_features(cv, "chapter")[0]["label"] == "III"

    def test_non_section_types_get_no_label_injected(self):
        unit = Unit(type="paragraph", tokens=[Token(text="x")])
        cv = _section_walk(unit, {"chapter": "label"})
        assert "label" not in _node_features(cv, "paragraph")[0]


class TestConvertDocumentsSections:
    """Real Text-Fabric walk — verifies the otext contract end to end (#174)."""

    def _bible_doc(self):
        def chapter(verses):
            return Unit(
                type="chapter",
                children=[
                    Unit(type="verse", tokens=[Token(text=f"word{i}", after=" ")])
                    for i in range(verses)
                ],
            )

        return Document(
            metadata=DocumentMetadata(title="Tiny Bible", source_format=SourceFormat.XML),
            units=[Unit(type="book", label="Genesis", children=[chapter(2), chapter(1)])],
        )

    def _convert(self, tmp_path, spec):
        return convert_documents(
            [self._bible_doc()],
            tmp_path / "tf",
            root_type="text",
            otype_for=lambda u: u.type,
            format_value="xml",
            source_label="test",
            section_spec=spec,
        )

    def test_multi_level_spec_lands_in_otext(self, tmp_path):
        spec = SectionSpec(
            types=("text", "book", "chapter", "verse"),
            features=("title", "label", "label", "label"),
        )
        self._convert(tmp_path, spec)
        otext = (tmp_path / "tf" / "otext.tf").read_text()
        assert "@sectionTypes=text,book,chapter,verse" in otext
        assert "@sectionFeatures=title,label,label,label" in otext

    def test_default_spec_is_root_with_title(self, tmp_path):
        self._convert(tmp_path, None)
        otext = (tmp_path / "tf" / "otext.tf").read_text()
        assert "@sectionTypes=text\n" in otext
        assert "@sectionFeatures=title\n" in otext

    def test_every_section_node_carries_its_label(self, tmp_path):
        spec = SectionSpec(
            types=("text", "book", "chapter", "verse"),
            features=("title", "label", "label", "label"),
        )
        self._convert(tmp_path, spec)
        label = (tmp_path / "tf" / "label.tf").read_text()
        # The book keeps its own label; unlabeled chapters and verses get
        # per-parent ordinals so T.sectionFromNode never hits an empty ref.
        assert "Genesis" in label
        values = [
            line.split("\t")[-1]
            for line in label.splitlines()
            if line and not line.startswith("@") and line.strip()
        ]
        assert values.count("1") >= 2  # chapter 1 + verse 1s
        assert "2" in values

    def test_root_label_falls_back_to_title(self, tmp_path):
        # A spec labeling the root by a feature metadata doesn't provide —
        # the walker backfills it from the document title.
        spec = SectionSpec(types=("text", "book"), features=("label", "label"))
        self._convert(tmp_path, spec)
        label = (tmp_path / "tf" / "label.tf").read_text()
        assert "Tiny Bible" in label
