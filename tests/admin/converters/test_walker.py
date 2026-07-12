"""_walker: metadata flattening, unit features, and the walk itself (fake CV)."""

from admin.converters._walker import (
    _unit_features,
    _walk_unit,
    metadata_features,
    set_features,
)
from admin.parsers.schema import DocumentMetadata, SourceFormat, Token, Unit


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
