"""The shared markup walker in _html.py and the HtmlParser."""

from admin.parsers import HtmlParser
from admin.parsers._html import (
    SKIP_TAGS,
    TEXT_UNIT_TYPE,
    attr_str,
    element_to_unit,
    top_level_units,
    unit_attrs,
)
from admin.parsers.schema import SourceFormat
from bs4 import BeautifulSoup


def _tag(html: str):
    """First tag of a parsed HTML fragment."""
    return BeautifulSoup(html, "html.parser").find(True)


class TestAttrHelpers:
    def test_attr_str_plain_value(self):
        assert attr_str(_tag('<div id="main"></div>'), "id") == "main"

    def test_attr_str_joins_multivalued(self):
        assert attr_str(_tag('<div class="a b c"></div>'), "class") == "a b c"

    def test_attr_str_empty_list_is_none(self):
        assert attr_str(_tag('<div class=""></div>'), "class") is None

    def test_attr_str_missing(self):
        assert attr_str(_tag("<div></div>"), "id") is None

    def test_unit_attrs_flattens_all(self):
        attrs = unit_attrs(_tag('<div class="a b" id="x" data-n="1"></div>'))
        assert attrs == {"class": "a b", "id": "x", "data-n": "1"}


class TestElementToUnit:
    def test_text_only_tag_becomes_leaf_with_tokens(self):
        unit = element_to_unit(_tag("<p>Hello world</p>"))
        assert unit.type == "p"
        assert [t.text for t in unit.tokens] == ["Hello", "world"]
        assert unit.children == []

    def test_mixed_content_preserves_document_order(self):
        unit = element_to_unit(_tag("<p>Hello <b>world</b> and me</p>"))
        assert [c.type for c in unit.children] == [TEXT_UNIT_TYPE, "b", TEXT_UNIT_TYPE]
        assert [t.text for t in unit.children[0].tokens] == ["Hello"]
        assert [t.text for t in unit.children[1].tokens] == ["world"]
        assert [t.text for t in unit.children[2].tokens] == ["and", "me"]

    def test_skip_tags_dropped(self):
        unit = element_to_unit(
            _tag("<div><script>evil()</script><p>keep</p><style>x{}</style></div>")
        )
        assert [c.type for c in unit.children] == ["p"]

    def test_head_is_not_skipped(self):
        # Regression guard: "head" was once in SKIP_TAGS and silently ate
        # TEI's <head> heading element (see packages/admin/CLAUDE.md).
        assert "head" not in SKIP_TAGS
        unit = element_to_unit(_tag("<div><head>Title</head><p>body</p></div>"))
        assert [c.type for c in unit.children] == ["head", "p"]

    def test_nested_attrs_preserved(self):
        unit = element_to_unit(_tag('<div id="outer"><span id="inner">x</span></div>'))
        assert unit.attrs["id"] == "outer"
        assert unit.children[0].attrs["id"] == "inner"


class TestTopLevelUnits:
    def test_only_direct_element_children(self):
        soup = BeautifulSoup(
            "<body>stray text<p>one</p><script>no</script><div>two</div></body>",
            "html.parser",
        )
        units = top_level_units(soup.find("body"))
        assert [u.type for u in units] == ["p", "div"]


class TestHtmlParser:
    HTML = """<html lang="en"><head>
      <title>My Page</title>
      <meta name="author" content="Jane Doe">
      <meta name="description" content="A test page">
    </head><body><h1>Hi</h1><p>Body text</p></body></html>"""

    def _write(self, tmp_path):
        f = tmp_path / "page.html"
        f.write_text(self.HTML)
        return str(f)

    def test_metadata(self, tmp_path):
        meta = HtmlParser().parse_metadata(self._write(tmp_path))
        assert meta.source_format == SourceFormat.HTML
        assert meta.title == "My Page"
        assert meta.creators == ["Jane Doe"]
        assert meta.language == "en"
        assert meta.description == "A test page"

    def test_iter_units_walks_body(self, tmp_path):
        units = list(HtmlParser().iter_units(self._write(tmp_path)))
        assert [u.type for u in units] == ["h1", "p"]

    def test_no_body_falls_back_to_soup(self, tmp_path):
        f = tmp_path / "frag.html"
        f.write_text("<p>only fragment</p>")
        units = list(HtmlParser().iter_units(str(f)))
        assert [u.type for u in units] == ["p"]

    def test_missing_metadata_is_none(self, tmp_path):
        f = tmp_path / "bare.html"
        f.write_text("<html><body><p>x</p></body></html>")
        meta = HtmlParser().parse_metadata(str(f))
        assert meta.title is None
        assert meta.creators == []
