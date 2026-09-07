"""Tests for the `/refs` router (`admin.services.reference_api`) and its
shared implementation (`admin.services.reference`).

Same harness as `test_corpus_detail_api.py`: a real, tiny `.corpus` archive is
built once through the converters and served by a fake storage, so the routes
run against a genuine cfabric payload and a genuine `manifest.yml`/`toc.yml`.
The text converter yields one `book` section (heading = the source filename
stem, `mini`) over `paragraph` and `word` nodes; word nodes 1..35, paragraphs
37..41, book 36.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from admin.converters._text_to_tf import convert_text_to_tf
from admin.converters.convert_to_corpus import convert_to_corpus
from admin.services import corpus_detail, reference, reference_api
from admin.services.storage import CorpusNotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient

ARCHIVE_NAME = "mini.corpus"


@pytest.fixture(scope="session")
def ref_archive_bytes(tmp_path_factory) -> bytes:
    work = tmp_path_factory.mktemp("reference-archive")
    src = work / "mini.txt"
    src.write_text("\n\n".join(f"Paragraph number {i} has some words here." for i in range(1, 6)))
    tf_dir = convert_text_to_tf(str(src), work / "tf")
    archive = convert_to_corpus(
        tf_dir,
        work / ARCHIVE_NAME,
        name="Mini Corpus",
        description="d",
        version="2.3.0",
        language="English",
        language_code="en",
        written_date="1851-10-18",
        author_ids=["melville"],
        publisher_id="harper",
    )
    return archive.read_bytes()


class FakeStorage:
    def __init__(self, archive_bytes: bytes):
        self._bytes = archive_bytes

    def download(self, filename, dest_dir):
        if filename != ARCHIVE_NAME:
            raise CorpusNotFoundError(f"No corpus named {filename!r}")
        dest = Path(dest_dir) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._bytes)
        return dest


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path, ref_archive_bytes):
    monkeypatch.setattr(corpus_detail, "_cache", {})
    monkeypatch.setattr(corpus_detail, "_HUB_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(corpus_detail, "corpus_storage", FakeStorage(ref_archive_bytes))
    monkeypatch.setattr(reference, "_adapters", {})


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(reference_api.router)
    return TestClient(app)


# ── create ─────────────────────────────────────────────────────────────────────


def test_create_reference_for_word_carries_version_and_metadata(client):
    resp = client.post("/refs", json={"corpus": "mini", "node": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ref"] == "mini@2.3.0/mini!word3"
    assert body["urn"] == "urn:tf:mini@2.3.0:mini!word3"
    assert body["node"] == 3 and body["otype"] == "word" and body["is_range"] is False
    assert body["sections"] == {"book": "mini"}
    assert body["first_slot"] == 3 and body["last_slot"] == 3
    corpus = body["corpus"]
    assert corpus["corpusId"] == "mini"
    assert corpus["title"] == "Mini Corpus"
    assert corpus["version"] == "2.3.0"
    assert corpus["year"] == "1851"
    assert corpus["authors"] == ["melville"] and corpus["publisher"] == "harper"
    assert corpus["language"] == "English"


def test_create_reference_accepts_filename_and_ranges(client):
    resp = client.post("/refs", json={"corpus": ARCHIVE_NAME, "node": 2, "end_node": 4})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ref"] == "mini@2.3.0/mini!word2-4"
    assert body["nodes"] == [2, 3, 4] and body["is_range"] is True
    assert body["last_slot"] == 4


def test_create_reference_for_section_node_is_bare_path(client):
    body = client.post("/refs", json={"corpus": "mini", "node": 36}).json()
    assert body["ref"] == "mini@2.3.0/mini" and body["otype"] == "book"


def test_create_reference_for_paragraph_indexes_within_book(client):
    body = client.post("/refs", json={"corpus": "mini", "node": 39}).json()
    assert body["ref"] == "mini@2.3.0/mini!paragraph3"


def test_create_reference_unknown_corpus_is_404(client):
    assert client.post("/refs", json={"corpus": "absent", "node": 1}).status_code == 404


def test_create_reference_unknown_node_is_404(client):
    assert client.post("/refs", json={"corpus": "mini", "node": 9999}).status_code == 404


# ── resolve ────────────────────────────────────────────────────────────────────


def test_resolve_fills_version_and_returns_node(client):
    resp = client.get("/refs/resolve", params={"ref": "mini/mini!paragraph3"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node"] == 39 and body["otype"] == "paragraph"
    assert body["ref"] == "mini@2.3.0/mini!paragraph3"
    assert body["input"] == "mini/mini!paragraph3"
    assert "Paragraph number 3" in body["text"]
    assert body["corpus"]["corpusId"] == "mini"


def test_resolve_accepts_urn_and_explicit_corpus(client):
    body = client.get("/refs/resolve", params={"ref": "urn:tf:mini:mini!word1"}).json()
    assert body["node"] == 1
    body = client.get("/refs/resolve", params={"ref": "mini!word5", "corpus": "mini"}).json()
    assert body["node"] == 5


def test_resolve_round_trips_create(client):
    created = client.post("/refs", json={"corpus": "mini", "node": 7, "end_node": 9}).json()
    resolved = client.get("/refs/resolve", params={"ref": created["ref"]}).json()
    assert resolved["nodes"] == [7, 8, 9] and resolved["ref"] == created["ref"]


def test_resolve_errors_map_to_status_codes(client):
    assert client.get("/refs/resolve", params={"ref": "mini/mini!word0"}).status_code == 400
    assert client.get("/refs/resolve", params={"ref": "mini!word1"}).status_code == 400  # no corpus
    assert client.get("/refs/resolve", params={"ref": "mini/nosuchbook"}).status_code == 404
    assert client.get("/refs/resolve", params={"ref": "mini/mini!word999"}).status_code == 404
    assert client.get("/refs/resolve", params={"ref": "mini/mini!verse1"}).status_code == 404
    assert client.get("/refs/resolve", params={"ref": "absent/mini!word1"}).status_code == 404
    resp = client.get("/refs/resolve", params={"ref": "mini@1.0.0/mini!word1"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["loaded"] == "2.3.0"


# ── shortcode ──────────────────────────────────────────────────────────────────


def test_shortcode_from_ref_normalises_and_builds_bundle(client):
    resp = client.get(
        "/refs/shortcode", params={"ref": "mini/mini!word3", "url_template": "https://app/r/{ref}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ref"] == "mini@2.3.0/mini!word3"
    assert body["label"] == "mini · word 3"
    assert body["compact"] == "mini wo3"
    assert body["url"] == "https://app/r/mini%402.3.0%2Fmini%21word3"
    assert body["pill"]["href"] == body["url"]
    assert body["markdown"] == f"[mini · word 3]({body['url']})"
    assert 'class="ref-pill"' in body["html"]


def test_shortcode_default_url_points_at_resolver(client):
    body = client.get("/refs/shortcode", params={"ref": "mini/mini"}).json()
    assert body["url"] == "/refs/resolve?ref=mini%402.3.0%2Fmini"
    assert body["label"] == "mini" and body["compact"] == "mini"


def test_shortcode_from_node(client):
    resp = client.post("/refs/shortcode", json={"corpus": "mini", "node": 2, "end_node": 4})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ref"] == "mini@2.3.0/mini!word2-4" and body["compact"] == "mini wo2-4"
    assert body["label"] == "mini · words 2-4"


def test_shortcode_unknown_library_corpus_is_404(client):
    # The library surface always verifies the reference against the archive
    # it names; only the runtime MCP surface formats foreign references as-is.
    assert (
        client.get("/refs/shortcode", params={"ref": "bhsa@2021/Deut:4:2!clause1"}).status_code
        == 404
    )
