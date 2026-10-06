"""Authorized validation through real archive loads, REST, and MCP."""

import json
import shutil
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from admin.converters.convert_to_corpus import convert_to_corpus
from admin.services.jobs import ConversionJob, JobStatus
from common.utils.request_context import current_owner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from corpora_py import auth
from corpora_py.ai import router, service
from corpora_py.ai.mcp import register_curation_tools
from corpora_py.ai.schemas import NodeScope
from corpora_py.ai.scope import scope_content_hash, scope_nodes


@pytest.fixture
def archive(tmp_path):
    dataset = tmp_path / "tf"
    dataset.mkdir()
    files = {
        "otype.tf": "@node\n@valueType=str\n\n1-8\tword\n9-12\tparagraph\n13-14\tchapter\n15\tbook\n",
        "oslots.tf": "@edge\n@valueType=str\n\n9\t1-2\n10\t3-4\n11\t5-6\n12\t7-8\n13\t1-4\n14\t5-8\n15\t1-8\n",
        "otext.tf": "@config\n@fmt:text-orig-full={text} \n@sectionTypes=book,chapter\n@sectionFeatures=book,chapter\n",
        "text.tf": "@node\n@valueType=str\n\n1\tone\n2\ttwo\n3\tthree\n4\tfour\n5\tfive\n6\tsix\n7\tseven\n8\teight\n",
        "book.tf": "@node\n@valueType=str\n\n15\tMini\n",
        "chapter.tf": "@node\n@valueType=int\n\n13\t1\n14\t2\n",
    }
    for name, content in files.items():
        (dataset / name).write_text(content)
    return convert_to_corpus(dataset, tmp_path / "mini.corpus", name="Mini", version="1.0")


@pytest.fixture
def loaded(archive):
    from cfabric import Fabric

    return Fabric(locations=str(archive.parent / "tf"), silent="deep").loadAll(silent="deep")


def scope(**overrides):
    return NodeScope(
        **{
            "corpus": "mini",
            "version": "v1.0",
            "level": "passage",
            "node_id": 9,
            "node_type": "paragraph",
            "label": "First paragraph",
            **overrides,
        }
    )


@pytest.fixture
def store(archive, monkeypatch):
    calls = []

    def download(name, dest_dir):
        calls.append((current_owner.get(), name))
        if current_owner.get() != "alice" or name not in ("mini", "mini.corpus"):
            raise service.storage.CorpusNotFoundError("secret backend path")
        dest = dest_dir / "mini.corpus"
        shutil.copyfile(archive, dest)
        return dest

    monkeypatch.setattr(service.storage, "corpus_storage", SimpleNamespace(download=download))
    monkeypatch.setattr(service.settings, "auth_required", True)
    return calls


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(auth, "verify_jwt", lambda token, **kwargs: {"sub": token})
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(router)
    return TestClient(app)


def post(client, owner="alice", **overrides):
    return client.post(
        "/ai/validate",
        headers={"Authorization": f"Bearer {owner}"},
        json={"scope": scope(**overrides).model_dump(mode="json")},
    )


@pytest.mark.parametrize(
    "selection,count",
    [
        ({}, 3),
        ({"level": "word", "node_id": 1, "node_type": "word"}, 1),
        ({"level": "section", "node_id": 13, "node_type": "chapter"}, 7),
        ({"level": "document", "node_id": 15, "node_type": "book"}, 15),
        ({"level": "corpus", "node_id": None, "node_type": None}, 15),
        ({"unit_range": {"start": 9, "end": 10}}, 6),
        ({"node_id": 13, "node_type": "chapter", "unit_range": {"start": 9, "end": 10}}, 6),
    ],
)
def test_real_authorized_scopes(client, store, selection, count):
    result = post(client, **selection)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "corpus": "mini",
        "version": "1.0",
        "checked_nodes": count,
        "findings": [],
    }
    assert store == [("alice", "mini")]
    assert current_owner.get() is None


def test_two_users_never_share_cached_corpus(client, store):
    assert post(client).status_code == 200
    denied = post(client, owner="bob")
    assert denied.status_code == 404
    assert denied.json() == {"detail": "Corpus not found"}
    assert store == [("alice", "mini"), ("bob", "mini")]


def test_no_identity_is_rejected_before_download(client, store):
    result = client.post("/ai/validate", json={"scope": scope().model_dump(mode="json")})
    assert result.status_code == 401
    assert not store


def test_service_fails_closed_without_middleware(store):
    with pytest.raises(service.CurationError) as error:
        service.validate_scope(scope())
    assert error.value.status == 403
    assert error.value.body["code"] == "forbidden"
    assert not store


@pytest.mark.parametrize(
    "corpus",
    ["../mini", "alice/mini", "/tmp/mini", "https://host/mini", "mini\\file", " mini", "job:nope"],
)
def test_client_cannot_supply_paths(client, store, corpus):
    assert post(client, corpus=corpus).status_code == 422
    assert not store


def test_version_drift_returns_frozen_error_shape(client):
    result = post(client, version="v1.1")
    assert result.status_code == 409
    assert result.json() == {
        "code": "stale",
        "reason": "Corpus version has changed",
        "retryable": False,
        "current_version": "1.0",
    }


def test_hash_checks_exact_selected_text(client, loaded):
    digest = scope_content_hash(loaded, scope_nodes(loaded, scope()))
    assert post(client, content_hash=digest).status_code == 200
    stale = post(client, content_hash="sha256:" + "0" * 64)
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale"
    assert post(client, content_hash="sha256:é").status_code == 409


@pytest.mark.parametrize(
    "selection",
    [
        {"node_id": 999},
        {"node_id": 0},
        {"node_type": "sentence"},
        {"level": "word"},
        {"level": "section"},
        {"level": "document"},
        {"level": "corpus"},
        {"unit_range": {"start": 9, "end": 11}},
        {"unit_range": {"start": 1, "end": 2}},
        {"unit_range": {"start": 9, "end": 13}},
        {"node_id": 12, "unit_range": {"start": 9, "end": 10}},
        {
            "level": "section",
            "node_id": 13,
            "node_type": "chapter",
            "unit_range": {"start": 9, "end": 10},
        },
    ],
)
def test_invalid_scopes_do_not_widen_selection(client, selection):
    assert post(client, **selection).status_code == 422


def test_ranges_follow_document_order_not_id_intervals(loaded, monkeypatch):
    # Unit IDs 9, 11, 10 appear in that document order. ID 11 must be included.
    slots = {9: (1,), 11: (2,), 10: (3,)}
    real_slots = loaded.E.oslots.s
    monkeypatch.setattr(loaded.E.oslots, "s", lambda n: slots.get(n, real_slots(n)))
    real_up, real_down = loaded.L.u, loaded.L.d
    monkeypatch.setattr(
        loaded.L,
        "u",
        lambda n, otype: (13,) if n in slots and otype == "chapter" else real_up(n, otype=otype),
    )
    monkeypatch.setattr(
        loaded.L,
        "d",
        lambda n, otype=None: (
            (9, 10, 11) if n == 13 and otype == "paragraph" else real_down(n, otype=otype)
        ),
    )
    result = scope_nodes(loaded, scope(unit_range={"start": 9, "end": 10}))
    assert {9, 10, 11} <= set(result)
    with pytest.raises(ValueError, match="document order"):
        scope_nodes(loaded, scope(node_id=10, unit_range={"start": 10, "end": 11}))


@pytest.fixture
def job(archive, monkeypatch):
    job = ConversionJob(
        id=str(uuid4()),
        source_format="plain",
        name="Mini",
        owner="alice",
        status=JobStatus.SUCCEEDED,
        result_path=archive,
    )

    def get(job_id):
        return job if job_id == job.id else None

    monkeypatch.setattr(
        service.jobs, "job_manager", SimpleNamespace(get=get, materialize=lambda j: j.result_path)
    )
    return job


def test_job_authorization_precedes_materializing(client, store, job, monkeypatch):
    result = post(client, corpus=f"job:{job.id}")
    assert result.status_code == 200, result.text
    monkeypatch.setattr(
        service.jobs.job_manager,
        "materialize",
        lambda j: pytest.fail("Unauthorized materialization"),
    )
    assert post(client, owner="bob", corpus=f"job:{job.id}").status_code == 404
    job.owner = None
    assert post(client, corpus=f"job:{job.id}").status_code == 404
    assert not store


def test_unknown_job_and_incomplete_conversion(client, job):
    assert post(client, corpus=f"job:{uuid4()}").status_code == 404
    job.status = JobStatus.RUNNING
    assert post(client, corpus=f"job:{job.id}").status_code == 409
    job.status = JobStatus.SUCCEEDED
    job.result_path = None
    assert post(client, corpus=f"job:{job.id}").status_code == 409


def test_auth_disabled_local_job_is_supported(client, job, monkeypatch):
    monkeypatch.setattr(service.settings, "auth_required", False)
    response = client.post(
        "/ai/validate", json={"scope": scope(corpus=f"job:{job.id}").model_dump(mode="json")}
    )
    assert response.status_code == 200


def test_storage_failure_does_not_expose_backend_details(client, monkeypatch):
    def download(*args, **kwargs):
        raise service.storage.StorageError("secret-token at private-bucket/user/path")

    monkeypatch.setattr(service.storage.corpus_storage, "download", download)
    response = post(client)
    assert response.status_code == 503
    assert "secret" not in response.text


async def test_mcp_matches_http_and_keeps_identity(client):
    expected = post(client).json()
    mcp = FastMCP("curation-test")
    register_curation_tools(mcp)
    owner_token = current_owner.set("alice")
    try:
        async with Client(mcp) as mcp_client:
            response = await mcp_client.call_tool(
                "validate_node", {"scope": scope().model_dump(mode="json")}
            )
            assert json.loads(response.content[0].text) == expected
            denied = await mcp_client.call_tool(
                "validate_node",
                {"scope": scope(version="2.0").model_dump(mode="json")},
                raise_on_error=False,
            )
            assert denied.is_error
            assert '"stale"' in denied.content[0].text
    finally:
        current_owner.reset(owner_token)


async def test_mcp_cannot_bypass_identity(store):
    mcp = FastMCP("curation-test")
    register_curation_tools(mcp)
    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "validate_node", {"scope": scope().model_dump(mode="json")}, raise_on_error=False
        )
        assert result.is_error
        assert '"forbidden"' in result.content[0].text
    assert not store


async def test_http_mcp_transport_propagates_each_verified_owner(store, monkeypatch):
    import httpx
    from fastmcp.client.transports import StreamableHttpTransport

    monkeypatch.setattr(auth, "verify_jwt", lambda token, **kwargs: {"sub": token})
    mcp = FastMCP("curation-http-test")
    register_curation_tools(mcp)
    mcp_app = mcp.http_app(path="/", stateless_http=True, json_response=True)
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.mount("/mcp", mcp_app)

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    async with mcp_app.lifespan(mcp_app):
        for owner, denied in (("alice", False), ("bob", True), ("alice", False)):
            transport = StreamableHttpTransport(
                "http://localhost/mcp/",
                headers={"Authorization": f"Bearer {owner}"},
                httpx_client_factory=client_factory,
            )
            async with Client(transport) as mcp_client:
                result = await mcp_client.call_tool(
                    "validate_node",
                    {"scope": scope().model_dump(mode="json")},
                    raise_on_error=False,
                )
                assert result.is_error is denied, result.content
    assert store == [("alice", "mini"), ("bob", "mini"), ("alice", "mini")]


def test_supabase_backend_reads_each_verified_owner_prefix(client, archive, monkeypatch):
    from admin.services.storage_supabase import SupabaseCorpusStorage

    urls = []

    def get(url, **kwargs):
        urls.append(url)
        owner = url.split("/")[-2]
        return SimpleNamespace(
            status_code=200 if owner == "alice" else 404,
            content=archive.read_bytes(),
            text="Not found",
        )

    backend = SupabaseCorpusStorage(
        bucket="private",
        url="https://store.example",
        key="test-key",
        session=SimpleNamespace(get=get),
    )
    monkeypatch.setattr(service.storage, "corpus_storage", backend)
    assert post(client).status_code == 200
    assert post(client, owner="bob").status_code == 404
    assert urls == [
        "https://store.example/storage/v1/object/private/alice/mini.corpus",
        "https://store.example/storage/v1/object/private/bob/mini.corpus",
    ]


def test_read_only_archive_is_unchanged(client, archive, monkeypatch):
    monkeypatch.setattr(service.settings, "hf_read_only", True)
    before = archive.read_bytes()
    assert post(client).status_code == 200
    assert archive.read_bytes() == before


def test_findings_use_declared_section_features(client, loaded, monkeypatch):
    import cfabric

    # The corpus metadata, not a client request, requires the chapter feature.
    original = loaded.Fs("chapter").v
    monkeypatch.setattr(loaded.Fs("chapter"), "v", lambda n: None if n == 13 else original(n))
    monkeypatch.setattr(
        cfabric, "Fabric", lambda **kw: SimpleNamespace(loadAll=lambda **kw: loaded)
    )
    response = post(client, level="section", node_id=13, node_type="chapter")
    assert response.status_code == 200
    (finding,) = response.json()["findings"]
    assert finding["rule"] == "FEATURE_MISSING"
    assert finding["node_id"] == 13
    assert finding["consequence"]
    assert finding["fixable"] is False
    assert post(client).json()["findings"] == []  # Paragraph scope excludes its parent.


def test_invalid_zip_is_rejected(client, archive):
    archive.write_bytes(b"not a zip")
    assert post(client).status_code == 422


def test_zip_path_escape_is_rejected(client, archive):
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr("../../escape.txt", "escape")
    response = post(client)
    assert response.status_code == 422
    assert not (archive.parent / "escape.txt").exists()


def test_threads_use_real_authorization_and_preserve_published_archive(
    client, archive, monkeypatch, tmp_path
):
    from corpora_py.ai import threads

    monkeypatch.setattr(service.settings, "ai_store", "sqlite")
    monkeypatch.setattr(service.settings, "ai_sqlite_path", str(tmp_path / "conversations.sqlite3"))
    before = archive.read_bytes()
    body = {"scope": scope().model_dump(mode="json")}
    headers = {"Authorization": "Bearer alice"}
    response = client.post("/ai/threads", json=body, headers=headers)
    assert response.status_code == 200
    thread = response.json()
    url = f"/ai/threads/{thread['id']}"
    assert client.get(url, headers={"Authorization": "Bearer bob"}).status_code == 404
    assert (
        client.post(
            url + "/sections",
            json={"scope": scope(version="old").model_dump(mode="json")},
            headers=headers,
        ).status_code
        == 409
    )
    threads._sqlite_store.cache_clear()
    assert client.get(url, headers=headers).json() == thread
    assert archive.read_bytes() == before

    def revoked(*args, **kwargs):
        raise service.storage.CorpusNotFoundError("revoked")

    monkeypatch.setattr(service.storage.corpus_storage, "download", revoked)
    assert client.get(url, headers=headers).status_code == 404
    threads._sqlite_store.cache_clear()
