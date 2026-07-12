"""Per-format otype mappings and the CONVERTERS registry contract."""

import pytest
from admin.converters import CONVERTERS
from admin.converters._epub_to_tf import _otype_for as epub_otype
from admin.converters._tei_to_tf import _otype_for as tei_otype
from admin.parsers import PARSERS
from admin.parsers.schema import SourceFormat, Unit


class TestEpubOtypes:
    @pytest.mark.parametrize(
        ("unit_type", "expected"),
        [
            ("chapter", "chapter"),
            ("p", "paragraph"),
            ("blockquote", "paragraph"),
            ("a", "link"),
            ("span", "element"),
            ("text", "element"),
        ],
    )
    def test_mapping(self, unit_type, expected):
        assert epub_otype(Unit(type=unit_type)) == expected


class TestTeiOtypes:
    @pytest.mark.parametrize(
        ("unit_type", "expected"),
        [("div", "div"), ("p", "paragraph"), ("l", "element"), ("seg", "element")],
    )
    def test_mapping(self, unit_type, expected):
        assert tei_otype(Unit(type=unit_type)) == expected


class TestRegistries:
    def test_converters_cover_expected_formats(self):
        assert set(CONVERTERS) == {
            SourceFormat.EPUB,
            SourceFormat.HTML,
            SourceFormat.PDF,
            SourceFormat.TEI,
            SourceFormat.PLAIN,
            SourceFormat.TF_ZIP,
        }

    def test_xml_deliberately_has_no_converter(self):
        # Generic XML has no fixed node vocabulary (packages/admin/CLAUDE.md);
        # a converter for it must be an explicit decision, not an accident.
        assert SourceFormat.XML not in CONVERTERS

    def test_parsers_cover_document_formats_not_tf_zip(self):
        assert SourceFormat.XML in PARSERS
        assert SourceFormat.TF_ZIP not in PARSERS  # importer, not a parser
