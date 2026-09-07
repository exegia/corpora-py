"""`common.utils.tfref` (reference grammar + resolution) and `refdisplay`.

The module is the same file the `skills/tf-reference-id` skill ships as
`scripts/tfref.py`; the first test pins that so the two cannot drift. The
resolution rules are exercised on the skill's own fixture (three section
levels, a title containing ':' and spaces, a clause and a phrase that straddle
a paragraph boundary, a sentence that straddles a chapter) through the stdlib
loader and, in the second test group, through a real cfabric api.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from common.utils import refdisplay, tfref

REPO = Path(__file__).resolve().parents[2]
SKILL_SCRIPT = REPO / "skills" / "tf-reference-id" / "scripts" / "tfref.py"
FIXTURE = REPO / "skills" / "tf-reference-id" / "assets" / "fixtures" / "spanning-mini"
MODULE = REPO / "packages" / "common" / "src" / "common" / "utils" / "tfref.py"

BOOK = "Moby-Dick: Or, The Whale"
BOOK_ENC = "Moby-Dick%3A Or, The Whale"


def test_module_is_identical_to_the_skill_script():
    assert MODULE.read_bytes() == SKILL_SCRIPT.read_bytes(), (
        "common/utils/tfref.py and skills/tf-reference-id/scripts/tfref.py drifted; "
        "copy one over the other."
    )


# ── grammar ───────────────────────────────────────────────────────────────────


def test_parse_short_form_decodes_and_types():
    r = tfref.parse(f"mobydick@0.1/{BOOK_ENC}:1:2!clause1")
    assert r.corpus == "mobydick" and r.version == "0.1"
    assert r.sections == (BOOK, "1", "2")
    assert (r.target_type, r.start, r.end, r.is_range) == ("clause", 1, 1, False)
    assert tfref.parse(r.short()) == r
    assert tfref.from_urn(r.urn()) == r
    assert r.urn() == "urn:tf:mobydick@0.1:Moby-Dick%3A%20Or,%20The%20Whale:1:2!clause1"


def test_parse_range_and_version_optional():
    r = tfref.parse("bhsa/Deut:4:2!word3-5")
    assert r.version is None and r.is_range and (r.start, r.end) == (3, 5)


@pytest.mark.parametrize("bad", ["", "x/A:1!word0", "x/A:1!word5-2", "x/A::1", "x/A:1!clause"])
def test_parse_rejects(bad):
    with pytest.raises(tfref.ParseError):
        tfref.parse(bad)


# ── resolution on the fixture (stdlib loader) ─────────────────────────────────


@pytest.fixture(scope="module")
def corpus():
    return tfref.load_corpus(str(FIXTURE))


def test_sections_and_int_typing(corpus):
    assert tfref.resolve(f"{BOOK_ENC}", corpus) == 28
    assert tfref.resolve(f"{BOOK_ENC}:2", corpus) == 27
    assert tfref.resolve(f"{BOOK_ENC}:1:2", corpus) == 24
    assert tfref.resolve(f"{BOOK_ENC}:01:2", corpus) == 24  # chapter feature is int


def test_anchor_to_first_slot(corpus):
    # clause 16 spans para (1,2) -> (2,1): addressed from (1,2) only
    assert tfref.resolve(f"{BOOK_ENC}:1:2!clause1", corpus) == 16
    assert tfref.resolve(f"{BOOK_ENC}:2:1!clause1", corpus) == 17
    with pytest.raises(tfref.IndexOutOfRange):
        tfref.resolve(f"{BOOK_ENC}:2:1!clause2", corpus)
    assert tfref.resolve(f"{BOOK_ENC}:1!clause2", corpus) == 16  # chapter-level index
    with pytest.raises(tfref.TypeNotInSection):
        tfref.resolve(f"{BOOK_ENC}:2!sentence1", corpus)  # sentence 14 starts in ch. 1


def test_serialize_round_trips_and_emits_version(corpus):
    assert tfref.serialize(16, corpus, corpus_id="m") == f"m@0.1/{BOOK_ENC}:1:2!clause1"
    assert tfref.serialize(24, corpus, corpus_id="m") == f"m@0.1/{BOOK_ENC}:1:2"
    assert tfref.serialize([1, 4], corpus, corpus_id="m") == f"m@0.1/{BOOK_ENC}:1:1!word1-4"
    for ref in [
        f"m@0.1/{BOOK_ENC}:1:1!word2",
        f"m@0.1/{BOOK_ENC}:1:2!phrase2",
        f"m@0.1/{BOOK_ENC}:2",
    ]:
        n = tfref.resolve(ref, corpus)
        assert tfref.serialize(n, corpus, corpus_id="m") == ref
    assert tfref.normalize(f"m/{BOOK_ENC}:1!clause2", corpus) == f"m@0.1/{BOOK_ENC}:1:2!clause1"


def test_version_mismatch_refuses(corpus):
    with pytest.raises(tfref.VersionMismatch) as exc:
        tfref.resolve(f"m@9/{BOOK_ENC}:1", corpus)
    assert (exc.value.wanted, exc.value.loaded) == ("9", "0.1")


# ── same rules through a real cfabric api ─────────────────────────────────────


@pytest.fixture(scope="module")
def cf_corpus(tmp_path_factory):
    cfabric = pytest.importorskip("cfabric")
    dst = tmp_path_factory.mktemp("spanning") / "spanning-mini"
    shutil.copytree(FIXTURE, dst)
    api = cfabric.Fabric(locations=str(dst), silent="deep").loadAll(silent="deep")
    assert not isinstance(api, bool)
    return tfref.load_corpus(api)


def test_cfabric_backend_agrees(cf_corpus, corpus):
    assert cf_corpus.version == "0.1"
    for ref in [
        f"{BOOK_ENC}:1:2!clause1",
        f"{BOOK_ENC}:2:1!clause1",
        f"{BOOK_ENC}:1!sentence2",
        f"{BOOK_ENC}:1:1!word1-4",
    ]:
        assert tfref.resolve(ref, cf_corpus) == tfref.resolve(ref, corpus)
    for node in (16, 17, 21, 24, 28, 10):
        assert tfref.serialize(node, cf_corpus) == tfref.serialize(node, corpus)


# ── presentation helpers ──────────────────────────────────────────────────────


def test_refdisplay_labels_and_shortcode(monkeypatch):
    r = tfref.parse("bhsa@2021/Deut:4:2!clause1")
    assert refdisplay.label_for(r) == "Deut 4:2 · clause 1"
    assert refdisplay.compact_for(r) == "Deut 4:2 cl1"
    assert refdisplay.compact_for(tfref.parse("bhsa/Deut:4:2!word3-5")) == "Deut 4:2 wo3-5"
    assert refdisplay.label_for(tfref.parse("bhsa/Deut:4")) == "Deut 4"
    payload = refdisplay.shortcode_payload(r, r.short(), url_template="https://x/r/{ref}")
    assert payload["url"] == "https://x/r/bhsa%402021%2FDeut%3A4%3A2%21clause1"
    assert payload["urn"] == "urn:tf:bhsa@2021:Deut:4:2!clause1"
    assert payload["pill"] == {
        "text": "Deut 4:2 cl1",
        "title": "Deut 4:2 · clause 1",
        "href": payload["url"],
    }
    assert payload["markdown"].startswith("[Deut 4:2 · clause 1](")


def test_refdisplay_corpus_metadata_shapes_manifest():
    meta = refdisplay.corpus_metadata(
        corpus_id="mini",
        manifest={
            "uid": "u1",
            "name": "Mini",
            "version": "1.0.0",
            "written_date": "2024-01-01",
            "language": "English",
        },
        toc={"authorId": "auth-1", "publisherId": "pub-1"},
    )
    assert meta["corpusId"] == "mini" and meta["title"] == "Mini" and meta["year"] == "2024"
    assert meta["authors"] == ["auth-1"] and meta["publisher"] == "pub-1"
    assert meta["version"] == "1.0.0" and meta["uid"] == "u1"
