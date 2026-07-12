"""XmlParser: generic XML to Unit tree."""

from admin.parsers import XmlParser
from admin.parsers.schema import SourceFormat


def _write(tmp_path, content):
    f = tmp_path / "doc.xml"
    f.write_text(content)
    return str(f)


def test_metadata_title_from_title_tag(tmp_path):
    src = _write(tmp_path, "<catalog><title>My Catalog</title><item/></catalog>")
    meta = XmlParser().parse_metadata(src)
    assert meta.source_format == SourceFormat.XML
    assert meta.title == "My Catalog"


def test_metadata_falls_back_to_root_name_and_attrs(tmp_path):
    src = _write(tmp_path, '<catalog version="2"><item/></catalog>')
    meta = XmlParser().parse_metadata(src)
    assert meta.title == "catalog"
    assert meta.extra == {"version": "2"}


def test_iter_units_yields_root_children(tmp_path):
    src = _write(
        tmp_path,
        '<catalog><item id="1">one</item><item id="2">two</item></catalog>',
    )
    units = list(XmlParser().iter_units(src))
    assert [u.type for u in units] == ["item", "item"]
    assert units[0].attrs == {"id": "1"}
    assert [t.text for t in units[1].tokens] == ["two"]


def test_leaf_only_document_yields_root_itself(tmp_path):
    src = _write(tmp_path, "<note>just text</note>")
    units = list(XmlParser().iter_units(src))
    assert len(units) == 1
    assert units[0].type == "note"
    assert [t.text for t in units[0].tokens] == ["just", "text"]
