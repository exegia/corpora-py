"""TeiParser: teiHeader metadata, head promotion, body walking."""

from admin.parsers import TeiParser
from admin.parsers._tei import _flatten_tokens, _promote_head
from admin.parsers.schema import SourceFormat, Token, Unit

TEI = """<?xml version="1.0"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>Sample Edition</title>
        <author>Alice</author>
        <author>Bob</author>
      </titleStmt>
      <publicationStmt>
        <publisher>Acme Press</publisher>
        <date>1901</date>
        <idno>XYZ-1</idno>
        <availability>Public Domain</availability>
      </publicationStmt>
    </fileDesc>
    <profileDesc><langUsage><language ident="grc">Greek</language></langUsage></profileDesc>
  </teiHeader>
  <text><body>
    <div type="chapter">
      <head>Chapter One</head>
      <p>In the beginning.</p>
    </div>
    <div type="chapter"><p>Second chapter text.</p></div>
  </body></text>
</TEI>"""


def _write(tmp_path, content=TEI):
    f = tmp_path / "doc.tei.xml"
    f.write_text(content)
    return str(f)


class TestMetadata:
    def test_full_header(self, tmp_path):
        meta = TeiParser().parse_metadata(_write(tmp_path))
        assert meta.source_format == SourceFormat.TEI
        assert meta.title == "Sample Edition"
        assert meta.creators == ["Alice", "Bob"]
        assert meta.language == "grc"
        assert meta.publisher == "Acme Press"
        assert meta.date == "1901"
        assert meta.identifier == "XYZ-1"
        assert meta.rights == "Public Domain"

    def test_no_header_returns_bare_metadata(self, tmp_path):
        meta = TeiParser().parse_metadata(
            _write(tmp_path, "<TEI><text><body><p>x</p></body></text></TEI>")
        )
        assert meta.source_format == SourceFormat.TEI
        assert meta.title is None


class TestIterUnits:
    def test_divisions_with_promoted_heads(self, tmp_path):
        units = list(TeiParser().iter_units(_write(tmp_path)))
        assert [u.type for u in units] == ["div", "div"]
        assert units[0].label == "Chapter One"
        # the <head> child was consumed into the label
        assert [c.type for c in units[0].children] == ["p"]
        assert units[1].label is None


class TestPromoteHead:
    def test_lifts_first_head_child(self):
        unit = Unit(
            type="div",
            children=[
                Unit(type="head", tokens=[Token(text="My"), Token(text="Title")]),
                Unit(type="p", tokens=[Token(text="body")]),
            ],
        )
        result = _promote_head(unit)
        assert result.label == "My Title"
        assert [c.type for c in result.children] == ["p"]

    def test_non_head_first_child_untouched(self):
        unit = Unit(type="div", children=[Unit(type="p")])
        assert _promote_head(unit).label is None
        assert len(unit.children) == 1

    def test_flatten_tokens_recurses_children(self):
        unit = Unit(
            type="head",
            children=[
                Unit(type="hi", tokens=[Token(text="Deep")]),
                Unit(type="hi", tokens=[Token(text="Title")]),
            ],
        )
        assert _flatten_tokens(unit) == ["Deep", "Title"]
