"""categorize/detect_category: role detection, spec derivation, overrides (issue #176)."""

from admin.converters._category import (
    categorize,
    detect_category,
    section_role,
)
from admin.parsers.schema import (
    CorpusCategory,
    Document,
    DocumentMetadata,
    SourceFormat,
    Token,
    Unit,
)


def _doc(units):
    return Document(
        metadata=DocumentMetadata(title="T", source_format=SourceFormat.XML),
        units=units,
    )


def _verse(n="1"):
    return Unit(type="verse", id=n, tokens=[Token(text="word", after=" ")])


def _chapter(children=None, **attrs):
    return Unit(type="chapter", attrs=attrs, children=children or [])


def _bible(books=1, chapters=2):
    def one_book():
        return Unit(
            type="book",
            label="Genesis",
            children=[_chapter([_verse()]) for _ in range(chapters)],
        )

    return _doc([one_book() for _ in range(books)])


class TestSectionRole:
    def test_explicit_unit_types(self):
        assert section_role(Unit(type="verse")) == "verse"
        assert section_role(Unit(type="chapter")) == "chapter"
        assert section_role(Unit(type="book")) == "book"

    def test_tei_div_type_attribute(self):
        assert section_role(Unit(type="div", attrs={"type": "chapter"})) == "chapter"
        assert section_role(Unit(type="div", attrs={"type": "Verse"})) == "verse"

    def test_surah_counts_as_chapter(self):
        assert section_role(Unit(type="div", attrs={"type": "surah"})) == "chapter"

    def test_level1_markdown_section_is_chapter(self):
        assert section_role(Unit(type="section", attrs={"level": "1"})) == "chapter"
        assert section_role(Unit(type="section", attrs={"level": "2"})) is None

    def test_plain_units_have_no_role(self):
        assert section_role(Unit(type="paragraph")) is None
        assert section_role(Unit(type="div")) is None


class TestDetectCategory:
    def test_verses_and_chapters_mean_religious(self):
        assert detect_category([_bible()]) is CorpusCategory.RELIGIOUS

    def test_chapters_without_verses_mean_book(self):
        doc = _doc([_chapter(), _chapter()])
        assert detect_category([doc]) is CorpusCategory.BOOK

    def test_single_chapter_is_just_a_document(self):
        assert detect_category([_doc([_chapter()])]) is CorpusCategory.DOCUMENT

    def test_flat_paragraphs_mean_document(self):
        doc = _doc([Unit(type="paragraph", tokens=[Token(text="x", after="")])])
        assert detect_category([doc]) is CorpusCategory.DOCUMENT


class TestCategorize:
    def test_religious_spec_declares_present_levels_only(self):
        # A single-book bible whose books ARE present declares all three;
        # the walker breaks on a declared level with zero nodes, so the
        # spec must track what actually occurs.
        effective, spec, _, warnings = categorize(
            [_bible()], None, root_type="text", base_otype_for=lambda u: "element"
        )
        assert effective is CorpusCategory.RELIGIOUS
        assert spec.types == ("text", "book", "chapter", "verse")
        assert spec.features == ("title", "label", "label", "label")
        assert warnings == []

    def test_bookless_bible_skips_the_book_level(self):
        doc = _doc([_chapter([_verse()]), _chapter([_verse()])])
        _, spec, _, _ = categorize(
            [doc], None, root_type="text", base_otype_for=lambda u: "element"
        )
        assert spec.types == ("text", "chapter", "verse")

    def test_document_spec_is_root_only(self):
        doc = _doc([Unit(type="paragraph", tokens=[Token(text="x", after="")])])
        effective, spec, _, _ = categorize(
            [doc], None, root_type="document", base_otype_for=lambda u: "element"
        )
        assert effective is CorpusCategory.DOCUMENT
        assert spec.types == ("document",)
        assert spec.features == ("title",)

    def test_downgrade_override_is_honored(self):
        # Flattening a bible to a plain book is always expressible.
        effective, spec, _, warnings = categorize(
            [_bible()],
            CorpusCategory.BOOK,
            root_type="text",
            base_otype_for=lambda u: "element",
        )
        assert effective is CorpusCategory.BOOK
        assert spec.types == ("text", "chapter")
        assert warnings == []

    def test_upgrade_override_downgrades_with_warning(self):
        doc = _doc([Unit(type="paragraph", tokens=[Token(text="x", after="")])])
        effective, _, _, warnings = categorize(
            [doc],
            CorpusCategory.RELIGIOUS,
            root_type="document",
            base_otype_for=lambda u: "element",
        )
        assert effective is CorpusCategory.DOCUMENT
        assert len(warnings) == 1
        assert "religious" in warnings[0]
        assert "document" in warnings[0]

    def test_max_category_caps_detection(self):
        effective, _, _, _ = categorize(
            [_bible()],
            None,
            root_type="document",
            base_otype_for=lambda u: "element",
            max_category=CorpusCategory.DOCUMENT,
        )
        assert effective is CorpusCategory.DOCUMENT

    def test_otype_for_promotes_declared_roles(self):
        _, _, otype_for, _ = categorize(
            [_bible()], None, root_type="text", base_otype_for=lambda u: "element"
        )
        assert otype_for(Unit(type="div", attrs={"type": "chapter"})) == "chapter"
        assert otype_for(Unit(type="verse")) == "verse"
        assert otype_for(Unit(type="p")) == "element"

    def test_otype_for_leaves_undeclared_roles_to_base(self):
        # Category document declares no book/chapter/verse levels, so role
        # units stay on the converter's own vocabulary.
        doc = _doc([Unit(type="paragraph", tokens=[Token(text="x", after="")])])
        _, _, otype_for, _ = categorize(
            [doc], None, root_type="document", base_otype_for=lambda u: "element"
        )
        assert otype_for(Unit(type="chapter")) == "element"
