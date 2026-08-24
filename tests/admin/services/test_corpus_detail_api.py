"""Tests for the corpus-detail HTTP endpoints (`admin.services.corpus_detail_api`).

The router contract is exercised with `corpus_detail.corpus_storage` monkeypatched
to a fake that serves a real, tiny `.corpus` archive built once via the converters
(`convert_text_to_tf` + `convert_to_corpus`) -- so index/content exercise a genuine
cfabric-loadable payload. The real Hub wrapper is covered by `test_storage.py`, and
auth gating is the combined app's `AuthMiddleware` concern (see
`tests/corpora_py/test_auth_middleware.py`), so the router is mounted bare here.

`corpus_detail`'s module-level `_cache`/`_HUB_CACHE_ROOT` persist across calls, so an
autouse fixture resets both per test (otherwise a cache hit skips `download` and the
suite becomes order-dependent -- e.g. the 404/503 cases would silently pass).
"""

import zipfile
from pathlib import Path

import pytest
import yaml
from admin.converters._text_to_tf import convert_text_to_tf
from admin.converters.convert_to_corpus import convert_to_corpus
from admin.services import corpus_detail, corpus_detail_api
from admin.services.storage import CorpusNotFoundError, StorageNotConfiguredError
from fastapi import FastAPI
from fastapi.testclient import TestClient

ARCHIVE_NAME = "mini.corpus"


@pytest.fixture(scope="session")
def corpus_archive_bytes(tmp_path_factory) -> bytes:
    """Build a real 5-paragraph `.corpus` archive once and return its bytes."""
    work = tmp_path_factory.mktemp("corpus-detail-archive")
    src = work / "mini.txt"
    src.write_text(
        "\n\n".join(f"Paragraph number {i} has some words here." for i in range(1, 6))
    )
    tf_dir = convert_text_to_tf(str(src), work / "tf")
    archive = convert_to_corpus(
        tf_dir,
        work / ARCHIVE_NAME,
        name="Mini Corpus",
        description="Original description",
        language="English",
        language_code="en",
    )
    return archive.read_bytes()


class FakeStorage:
    """Serves the prebuilt archive for `mini.corpus`; records uploads."""

    def __init__(self, archive_bytes: bytes):
        self._bytes = archive_bytes
        self.uploads: list[tuple[Path, str | None]] = []

    def download(self, filename, dest_dir):
        if filename != ARCHIVE_NAME:
            raise CorpusNotFoundError(f"No corpus named {filename!r}")
        dest = Path(dest_dir) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._bytes)
        return dest

    def upload(self, local_path, filename=None):
        self.uploads.append((Path(local_path), filename))
        # Serve the re-uploaded archive on subsequent downloads, like the Hub
        # would -- writer tests can then verify their change round-trips.
        self._bytes = Path(local_path).read_bytes()
        return None


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Reset the module-level cache + cache root so tests don't cross-contaminate."""
    monkeypatch.setattr(corpus_detail, "_cache", {})
    monkeypatch.setattr(corpus_detail, "_HUB_CACHE_ROOT", tmp_path / "cache")


@pytest.fixture
def fake_storage(monkeypatch, corpus_archive_bytes) -> FakeStorage:
    fake = FakeStorage(corpus_archive_bytes)
    monkeypatch.setattr(corpus_detail, "corpus_storage", fake)
    return fake


@pytest.fixture
def client(fake_storage) -> TestClient:
    app = FastAPI()
    app.include_router(corpus_detail_api.router)
    return TestClient(app)


# ── Manifest (GET) ─────────────────────────────────────────────────────────────


def test_get_manifest_passes_through_all_keys(client):
    resp = client.get(f"/storage/{ARCHIVE_NAME}/manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Mini Corpus"
    assert body["description"] == "Original description"
    # Non-editable keys the PATCH surface never touches are preserved verbatim.
    assert body["format"] == "corpus"
    assert body["tocFile"] == "toc.yml"
    assert "uid" in body


def test_get_manifest_unknown_filename_is_404(client):
    assert client.get("/storage/absent.corpus/manifest").status_code == 404


def test_get_manifest_storage_not_configured_is_503(client, fake_storage, monkeypatch):
    def boom(filename, dest_dir):
        raise StorageNotConfiguredError("set HF_STORAGE_REPO")

    monkeypatch.setattr(fake_storage, "download", boom)
    assert client.get(f"/storage/{ARCHIVE_NAME}/manifest").status_code == 503


# ── Manifest (PATCH) ───────────────────────────────────────────────────────────


def test_patch_manifest_updates_subset_and_preserves_rest(client, fake_storage):
    resp = client.patch(
        f"/storage/{ARCHIVE_NAME}/manifest",
        json={"description": "Edited description", "category": "poetry"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Changed fields land...
    assert body["description"] == "Edited description"
    assert body["category"] == "poetry"
    # ...untouched editable + non-editable keys survive.
    assert body["name"] == "Mini Corpus"
    assert body["language"] == "English"
    assert body["format"] == "corpus"
    assert "uid" in body

    # The archive was re-uploaded under its own name...
    assert fake_storage.uploads
    assert fake_storage.uploads[-1][1] == ARCHIVE_NAME
    # ...and the local cache was invalidated so the next read re-fetches.
    assert ARCHIVE_NAME not in corpus_detail._cache


def test_patch_manifest_empty_body_is_422(client):
    assert client.patch(f"/storage/{ARCHIVE_NAME}/manifest", json={}).status_code == 422


# ── Index ──────────────────────────────────────────────────────────────────────


def test_get_index_shape(client):
    resp = client.get(f"/storage/{ARCHIVE_NAME}/index")
    assert resp.status_code == 200
    body = resp.json()

    # toc.yml passthrough (a dict, not None, for a real archive).
    assert isinstance(body["toc"], dict)

    sections = body["sections"]
    assert sections["levels"] == ["book"]
    assert len(sections["items"]) == 1
    item = sections["items"][0]
    assert set(item) >= {
        "title",
        "ref",
        "children",
        "otype",
        "child_count",
        "nodes",
        "words",
        "truncated",
    }
    # Single-level corpus: top items have no child sections.
    assert item["children"] == []
    assert item["child_count"] == 0
    assert item["truncated"] is False
    assert item["otype"] == "book"
    assert isinstance(item["words"], int) and item["words"] > 0

    node_types = body["node_types"]
    assert all(
        set(nt) >= {"type", "count", "avg_slots", "is_slot"} for nt in node_types
    )
    counts = {nt["type"]: nt["count"] for nt in node_types}
    assert counts["book"] == 1
    assert counts["paragraph"] == 5
    by_type = {nt["type"]: nt for nt in node_types}
    assert by_type["word"]["is_slot"] is True
    assert by_type["word"]["avg_slots"] == 1
    assert by_type["book"]["is_slot"] is False
    assert by_type["book"]["avg_slots"] >= 1


# ── Content ────────────────────────────────────────────────────────────────────


def test_get_content_whole_corpus_paginates(client):
    resp = client.get(f"/storage/{ARCHIVE_NAME}/content", params={"limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ref"] is None
    assert body["total"] == 5
    assert body["offset"] == 0
    assert body["limit"] == 2
    assert body["next_offset"] == 2
    assert len(body["passages"]) == 2
    assert all(set(p) >= {"node", "ref", "text", "tokens"} for p in body["passages"])
    assert all(isinstance(p["node"], int) for p in body["passages"])
    assert body["passages"][0]["text"]  # non-empty
    tokens = body["passages"][0]["tokens"]
    assert tokens
    assert all(set(t) >= {"text", "after", "node"} for t in tokens)
    assert all(isinstance(t["node"], int) for t in tokens)


def test_get_content_last_page_has_no_next_offset(client):
    resp = client.get(
        f"/storage/{ARCHIVE_NAME}/content", params={"offset": 4, "limit": 2}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["passages"]) == 1
    assert body["next_offset"] is None


def test_get_content_limit_is_clamped_to_200(client):
    resp = client.get(f"/storage/{ARCHIVE_NAME}/content", params={"limit": 1000})
    assert resp.status_code == 200
    assert resp.json()["limit"] == 200


def test_get_content_limit_is_clamped_up_to_1(client):
    resp = client.get(f"/storage/{ARCHIVE_NAME}/content", params={"limit": 0})
    assert resp.status_code == 200
    assert resp.json()["limit"] == 1


def test_get_content_bad_ref_is_404(client):
    resp = client.get(
        f"/storage/{ARCHIVE_NAME}/content", params={"ref": "Nonexistent 999"}
    )
    assert resp.status_code == 404


def test_index_ref_round_trips_into_content(client):
    """The ref the index emits must resolve back to real passages in content."""
    index = client.get(f"/storage/{ARCHIVE_NAME}/index").json()
    ref = index["sections"]["items"][0]["ref"]

    resp = client.get(f"/storage/{ARCHIVE_NAME}/content", params={"ref": ref})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ref"] == ref
    assert body["total"] == 5
    assert body["passages"]


def test_get_sections_lists_top_level(client):
    resp = client.get(f"/storage/{ARCHIVE_NAME}/sections")
    assert resp.status_code == 200
    body = resp.json()
    assert body["parent"] is None
    assert body["levels"] == ["book"]
    assert body["total"] == 1
    assert body["next_offset"] is None
    item = body["items"][0]
    assert item["otype"] == "book"
    assert item["child_count"] == 0
    assert set(item) >= {"title", "ref", "otype", "child_count", "nodes", "words"}


def test_get_sections_unknown_parent_is_404(client):
    assert (
        client.get(
            f"/storage/{ARCHIVE_NAME}/sections",
            params={"parent": "Nonexistent 999"},
        ).status_code
        == 404
    )


def test_get_sections_lowest_level_has_no_children(client):
    index = client.get(f"/storage/{ARCHIVE_NAME}/index").json()
    ref = index["sections"]["items"][0]["ref"]
    body = client.get(
        f"/storage/{ARCHIVE_NAME}/sections", params={"parent": ref}
    ).json()
    assert body["parent"] == ref
    assert body["items"] == []
    assert body["total"] == 0


# ── Nodes (GET) ────────────────────────────────────────────────────────────────


def _first_passage_node(client) -> int:
    """A real passage node id straight from the content endpoint."""
    body = client.get(f"/storage/{ARCHIVE_NAME}/content", params={"limit": 1}).json()
    return body["passages"][0]["node"]


def test_get_node_shape(client):
    node = _first_passage_node(client)
    resp = client.get(f"/storage/{ARCHIVE_NAME}/nodes/{node}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["node"] == node
    assert body["otype"] == "paragraph"
    assert body["is_slot"] is False
    assert body["slot_type"] == "word"
    # A paragraph spans a real slot range, in order.
    assert isinstance(body["first_slot"], int)
    assert isinstance(body["last_slot"], int)
    assert body["first_slot"] <= body["last_slot"]
    assert body["text"]
    assert isinstance(body["features"], dict)
    assert body["annotation"] is None
    assert set(body["node_types"]) >= {"book", "paragraph", "word"}
    assert isinstance(body["context"], list)
    assert body["occurrences"] >= 1
    assert body["occurrences_in_section"] >= 1
    assert body["occurrences_in_section"] <= body["occurrences"]


def test_get_node_slot_node(client):
    """Slot nodes report is_slot=True and span exactly themselves."""
    detail = client.get(
        f"/storage/{ARCHIVE_NAME}/nodes/{_first_passage_node(client)}"
    ).json()
    slot = detail["first_slot"]

    body = client.get(f"/storage/{ARCHIVE_NAME}/nodes/{slot}").json()
    assert body["otype"] == "word"
    assert body["is_slot"] is True
    assert body["first_slot"] == body["last_slot"] == slot
    assert body["context"]
    assert any(row["otype"] == "paragraph" for row in body["context"])
    assert body["occurrences"] >= 1


def test_get_node_unknown_node_is_404(client):
    assert client.get(f"/storage/{ARCHIVE_NAME}/nodes/999999").status_code == 404


def test_get_node_unknown_filename_is_404(client):
    assert client.get("/storage/absent.corpus/nodes/1").status_code == 404


# ── Nodes (PATCH) ──────────────────────────────────────────────────────────────


def test_patch_node_records_annotation_and_republishes(client, fake_storage):
    node = _first_passage_node(client)
    resp = client.patch(
        f"/storage/{ARCHIVE_NAME}/nodes/{node}",
        json={"otype": "clause", "note": "converter over-grouped this"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["node"] == node
    assert body["otype"] == "clause"
    assert body["note"] == "converter over-grouped this"
    # The converter's original type is recorded server-side for provenance.
    assert body["converted_otype"] == "paragraph"
    assert body["updated_at"]

    # The archive was re-uploaded and the cache invalidated (same contract as
    # a manifest PATCH).
    assert fake_storage.uploads
    assert fake_storage.uploads[-1][1] == ARCHIVE_NAME
    assert ARCHIVE_NAME not in corpus_detail._cache


def test_patch_node_annotation_round_trips_into_get(client, fake_storage):
    """After a PATCH, a fresh download of the archive carries the annotation.

    The fake storage serves the last-uploaded bytes (like the Hub), and the
    PATCH invalidated the cache -- so the GET below re-downloads the
    re-published archive and must find the sidecar entry in it.
    """
    node = _first_passage_node(client)
    client.patch(f"/storage/{ARCHIVE_NAME}/nodes/{node}", json={"otype": "clause"})

    body = client.get(f"/storage/{ARCHIVE_NAME}/nodes/{node}").json()
    assert body["annotation"]["otype"] == "clause"
    assert body["annotation"]["converted_otype"] == "paragraph"

    # A second PATCH merges into the existing entry rather than replacing it.
    client.patch(f"/storage/{ARCHIVE_NAME}/nodes/{node}", json={"note": "2nd pass"})
    body = client.get(f"/storage/{ARCHIVE_NAME}/nodes/{node}").json()
    assert body["annotation"]["otype"] == "clause"
    assert body["annotation"]["note"] == "2nd pass"
    assert body["annotation"]["converted_otype"] == "paragraph"


def test_patch_node_empty_body_is_422(client):
    node = _first_passage_node(client)
    resp = client.patch(f"/storage/{ARCHIVE_NAME}/nodes/{node}", json={})
    assert resp.status_code == 422


def test_patch_node_unknown_node_is_404(client):
    resp = client.patch(
        f"/storage/{ARCHIVE_NAME}/nodes/999999", json={"otype": "word"}
    )
    assert resp.status_code == 404


# ── read-only mode (HF_READ_ONLY) ─────────────────────────────────────────────
# Both PATCH routes re-upload the archive to the Hub, so they carry the shared
# `require_writable` guard: 403 up front, no download/extract, no re-upload.


def test_read_only_patch_manifest_is_403(client, fake_storage, monkeypatch):
    from admin.services import storage_api

    monkeypatch.setattr(storage_api.settings, "hf_read_only", True)
    resp = client.patch(f"/storage/{ARCHIVE_NAME}/manifest", json={"name": "New"})
    assert resp.status_code == 403
    assert fake_storage.uploads == []


def test_read_only_patch_node_is_403(client, fake_storage, monkeypatch):
    from admin.services import storage_api

    monkeypatch.setattr(storage_api.settings, "hf_read_only", True)
    resp = client.patch(f"/storage/{ARCHIVE_NAME}/nodes/1", json={"note": "x"})
    assert resp.status_code == 403
    assert fake_storage.uploads == []


def test_read_only_still_allows_manifest_read(client, monkeypatch):
    from admin.services import storage_api

    monkeypatch.setattr(storage_api.settings, "hf_read_only", True)
    assert client.get(f"/storage/{ARCHIVE_NAME}/manifest").status_code == 200


# ── Versions ───────────────────────────────────────────────────────────────────


def test_get_versions_has_a_current_row(client):
    resp = client.get(f"/storage/{ARCHIVE_NAME}/versions")
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert versions
    assert any(row.get("current") for row in versions)
    assert all({"id", "label", "title", "at", "current", "notes"} <= set(row) for row in versions)
    row = next(v for v in versions if v.get("current"))
    assert row["id"] == "v1.0"
    assert {f["path"] for f in row["files"]} >= {"manifest.yml", "toc.yml", "corpora/"}
    assert "author" in row
    assert "approved_by" in row
    assert "sha" not in row


def test_get_versions_passes_through_sidecar_fields(tmp_path, monkeypatch):
    """history.yml files/author/snapshot_key are returned as-is; sha is not required."""
    monkeypatch.setattr(corpus_detail, "_local_archives", {})
    archive = tmp_path / "sidecar.corpus"
    history = {
        "versions": [
            {
                "id": "v1.0",
                "label": "v1.0",
                "title": "Converted",
                "at": "2026-01-01T00:00:00+00:00",
                "current": True,
                "snapshot_key": "conversion-jobs/j1/v1.0.corpus",
                "files": [{"path": "manifest.yml", "kind": "modified"}],
                "author": {"sub": "alice", "name": "Alice"},
                "approved_by": None,
                "notes": ["hi"],
            }
        ]
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.yml", "name: x\n")
        zf.writestr("toc.yml", "uid: y\n")
        zf.writestr("corpora/otype.tf", "x")
        zf.writestr("history.yml", yaml.safe_dump(history))
    key = corpus_detail.register_local_archive("sidecar.corpus", archive)
    row = corpus_detail.get_versions(key)["versions"][0]
    assert row["files"] == [{"path": "manifest.yml", "kind": "modified"}]
    assert row["author"] == {"sub": "alice", "name": "Alice"}
    assert row["snapshot_key"] == "conversion-jobs/j1/v1.0.corpus"
    assert row["approved_by"] is None
    assert "sha" not in row


def test_restore_is_501(client):
    resp = client.post(f"/storage/{ARCHIVE_NAME}/restore")
    assert resp.status_code == 501
