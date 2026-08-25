"""markdown_to_units: heading nesting, paragraph splitting, fence handling."""

from admin.parsers._markdown import markdown_to_units


def _flat_text(unit):
    return "".join(t.text + t.after for t in unit.tokens)


class TestHeadings:
    def test_heading_becomes_section_with_label_and_level(self):
        units = markdown_to_units("# Title\n\nSome text here.\n")
        assert len(units) == 1
        section = units[0]
        assert section.type == "section"
        assert section.label == "Title"
        assert section.attrs["level"] == "1"

    def test_deeper_heading_nests_under_shallower(self):
        units = markdown_to_units("# Book\n\n## Chapter One\n\nText.\n")
        assert [u.label for u in units] == ["Book"]
        (chapter,) = units[0].children
        assert chapter.label == "Chapter One"
        assert chapter.attrs["level"] == "2"

    def test_same_level_headings_are_siblings(self):
        units = markdown_to_units("## A\n\nx\n\n## B\n\ny\n")
        assert [u.label for u in units] == ["A", "B"]

    def test_returning_to_shallower_level_pops_the_stack(self):
        text = "# Book\n\n## One\n\nx\n\n# Book Two\n\ny\n"
        units = markdown_to_units(text)
        assert [u.label for u in units] == ["Book", "Book Two"]

    def test_trailing_hashes_stripped_from_label(self):
        units = markdown_to_units("## Closed Heading ##\n")
        assert units[0].label == "Closed Heading"


class TestParagraphs:
    def test_blank_line_splits_paragraphs(self):
        units = markdown_to_units("First block.\n\nSecond block.\n")
        assert [u.type for u in units] == ["paragraph", "paragraph"]
        assert "First" in _flat_text(units[0])
        assert "Second" in _flat_text(units[1])

    def test_paragraph_tokens_are_words(self):
        units = markdown_to_units("alpha beta gamma\n")
        assert [t.text for t in units[0].tokens] == ["alpha", "beta", "gamma"]

    def test_empty_input_yields_no_units(self):
        assert markdown_to_units("") == []
        assert markdown_to_units("\n\n\n") == []


class TestCodeFences:
    def test_hash_inside_fence_is_not_a_heading(self):
        text = "```\n# not a heading\n```\n"
        units = markdown_to_units(text)
        assert all(u.type != "section" for u in units)

    def test_fence_content_kept_as_text(self):
        text = "para\n\n```\ncode line\n```\n"
        units = markdown_to_units(text)
        joined = " ".join(_flat_text(u) for u in units)
        assert "code" in joined
