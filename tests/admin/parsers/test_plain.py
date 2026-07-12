"""PlainTextParser: paragraph splitting, ids, title derivation."""

from admin.parsers import PlainTextParser
from admin.parsers.schema import SourceFormat


def _write(tmp_path, text, name="story.txt"):
    f = tmp_path / name
    f.write_text(text)
    return str(f)


def test_paragraphs_split_on_blank_lines(tmp_path):
    src = _write(tmp_path, "First para line one.\nLine two.\n\nSecond para.")
    units = list(PlainTextParser().iter_units(src))
    assert len(units) == 2
    assert all(u.type == "paragraph" for u in units)
    assert [t.text for t in units[1].tokens] == ["Second", "para."]


def test_blank_blocks_skipped_ids_non_contiguous(tmp_path):
    # "a\n\n\n\nb" splits into ["a", "", "b"] -- the empty middle block is
    # skipped but still consumes an index, so ids are 0 and 2.
    src = _write(tmp_path, "alpha\n\n\n\nbeta")
    units = list(PlainTextParser().iter_units(src))
    assert [u.id for u in units] == ["0", "2"]


def test_metadata_title_from_filename_stem(tmp_path):
    meta = PlainTextParser().parse_metadata(_write(tmp_path, "x", name="moby-dick.txt"))
    assert meta.source_format == SourceFormat.PLAIN
    assert meta.title == "moby-dick"


def test_title_from_url_stem(monkeypatch):
    parser = PlainTextParser()
    meta = parser.parse_metadata("https://example.test/texts/iliad.txt?v=2")
    assert meta.title == "iliad"


def test_whitespace_only_document_yields_nothing(tmp_path):
    src = _write(tmp_path, "   \n\n   \n\n")
    assert list(PlainTextParser().iter_units(src)) == []
