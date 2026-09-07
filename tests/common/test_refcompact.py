"""`common.utils.refcompact`: the compact positional token as a serialization
of a resolved tfref reference, plus the stdlib-loader regression it surfaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from common.utils import refcompact, tfref

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "skills" / "tf-reference-id" / "assets" / "fixtures" / "spanning-mini"


@pytest.fixture(scope="module")
def corpus():
    return tfref.load_corpus(str(FIXTURE))


@pytest.mark.parametrize(
    ("node", "token"),
    [
        (28, "comoby-dick_bk001"),
        (24, "comoby-dick_bk001_ch001_pa002"),
        (16, "comoby-dick_bk001_ch001_pa002_cl001"),  # spans into ch2 -> anchored where it starts
        (17, "comoby-dick_bk001_ch002_pa001_cl001"),
        (21, "comoby-dick_bk001_ch001_pa002_ph002"),
        (14, "comoby-dick_bk001_ch001_pa002_st001"),
        (10, "comoby-dick_bk001_ch002_pa001_wo002"),
    ],
)
def test_round_trip_matches_tfref_numbering(corpus, node, token):
    assert refcompact.to_compact(node, corpus, "moby_dick") == token  # `_` folded to `-`
    assert refcompact.from_compact(token, corpus) == ("moby-dick", node)
    # Same ordinal the short form uses for the sub-unit.
    short = tfref.serialize(node, corpus)
    r = tfref.parse(short)
    if r.target_type:
        assert token.endswith(f"{refcompact.UNIT_PREFIXES[r.target_type]}{r.start:03d}")


def test_ranges_and_skipped_levels(corpus):
    assert refcompact.to_compact([1, 4], corpus, "m") == "com_bk001_ch001_pa001_wo001-004"
    assert refcompact.from_compact("com_bk001_ch001_pa001_wo001-004", corpus) == ("m", [1, 2, 3, 4])
    # Skipping counts under the nearest present ancestor (spec rule 1).
    assert refcompact.from_compact("com_bk001_pa003", corpus) == ("m", 25)
    assert refcompact.from_compact("com_bk001_cl002", corpus) == ("m", 16)
    assert refcompact.from_compact("com_bk001_st002_cl001", corpus) == ("m", 16)


@pytest.mark.parametrize(
    ("token", "exc"),
    [
        ("nope", tfref.ParseError),
        ("com", tfref.ParseError),
        ("com_cl001", tfref.ParseError),
        ("com_bk001_ch001_bk001", tfref.ParseError),
        ("com_bk001_pa009", tfref.IndexOutOfRange),
        ("com_bk001_ch001_pa001_cl001-002_wo001", tfref.ParseError),
    ],
)
def test_rejects(corpus, token, exc):
    with pytest.raises(exc):
        refcompact.from_compact(token, corpus)


def test_is_compact_and_slug():
    assert refcompact.is_compact("cobhsa_bk005_ch004_pa002_cl001")
    assert not refcompact.is_compact("bhsa@2021/Deut:4:2!clause1")
    assert refcompact.slug_of("cobhsa_bk005") == "bhsa"


def test_pa_is_a_block_unit_on_shallow_corpora(tmp_path):
    """Converter output shape: one `book` section over `paragraph` nodes, so
    `pa` binds to the paragraph node type rather than a third section level."""
    d = tmp_path / "tf"
    d.mkdir()
    (d / "otype.tf").write_text("@node\n@valueType=str\n\n1-6\tword\n7-8\tparagraph\n9\tbook\n")
    (d / "oslots.tf").write_text("@edge\n@valueType=str\n\n1-3\n4-6\n9\t1-6\n")
    (d / "otext.tf").write_text("@config\n@sectionTypes=book\n@sectionFeatures=title\n\n")
    (d / "title.tf").write_text("@node\n@valueType=str\n\n9\tmini\n")
    c = tfref.load_corpus(str(d))
    assert c.slots(9) == (1, 6) and c.slots(7) == (1, 3) and c.slots(8) == (4, 6)
    assert refcompact.to_compact(8, c, "mini") == "comini_bk001_pa002"
    assert refcompact.from_compact("comini_bk001_pa002", c) == ("mini", 8)
    assert refcompact.from_compact("comini_bk001_pa002_wo002", c) == ("mini", 5)
    assert tfref.serialize(8, c, corpus_id="mini") == "mini/mini!paragraph2"


def test_explicit_spec_moves_implicit_cursor(tmp_path):
    d = tmp_path / "tf"
    d.mkdir()
    (d / "otype.tf").write_text("@node\n@valueType=str\n\n1-6\tword\n7\tbook\n8-9\tparagraph\n")
    # Explicit node 7 first, then bare lines: they are nodes 8 and 9.
    (d / "oslots.tf").write_text("@edge\n@valueType=str\n\n7\t1-6\n1-3\n4-6\n")
    (d / "otext.tf").write_text("@config\n@sectionTypes=book\n@sectionFeatures=title\n\n")
    (d / "title.tf").write_text("@node\n@valueType=str\n\n7\tmini\n")
    c = tfref.load_corpus(str(d))
    assert c.slots(7) == (1, 6) and c.slots(8) == (1, 3) and c.slots(9) == (4, 6)
