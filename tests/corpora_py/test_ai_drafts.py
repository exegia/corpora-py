"""Owned provisioning and reader/export round trips over real SQL and archives."""

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import yaml
from admin.services import corpus_detail, jobs
from common.utils.request_context import current_owner
from fastmcp import Client, FastMCP
from test_ai_archive_editor import selection as selection
from test_ai_hosted_storage import literal
from test_ai_hosted_storage import postgres as postgres
from test_ai_mutations import DatabaseThreads
from test_ai_mutations import database as previous_database  # noqa: F401
from test_ai_mutations import setup as setup
from test_ai_service import archive as archive

from corpora_py.ai import drafts, service, threads
from corpora_py.ai.mcp import register_curation_tools
from corpora_py.ai.wal_sqlite import JournalUnavailableError


@pytest.fixture(scope="module")
def database(previous_database):  # noqa: F811 - imported pytest fixture
    query = previous_database
    # Expand the minimal fixture to the verified live document columns/policies.
    query("""ALTER TABLE public.corpus_documents ADD COLUMN name text NOT NULL DEFAULT 'fixture',
        ADD COLUMN source text NOT NULL DEFAULT 'upload' CHECK(source IN ('upload','huggingface')), ADD COLUMN path text NOT NULL DEFAULT 'fixture',
        ADD COLUMN filename text, ADD COLUMN job_id text, ADD COLUMN status text CHECK(status IN ('converted','uploaded'));
        ALTER TABLE public.corpus_documents ENABLE ROW LEVEL SECURITY;
        GRANT ALL ON public.corpus_documents TO anon,authenticated;
        CREATE POLICY fixture_documents_allow ON public.corpus_documents FOR ALL TO PUBLIC USING(true) WITH CHECK(true);
    """)
    migration = (
        Path(__file__).resolve().parents[2]
        / "packages/admin/sql/migrations/20260918180400_ai_owned_drafts.sql"
    )
    query(migration.read_text())
    return query


class DraftThreads(DatabaseThreads):
    def create(self, record):
        values = ",".join(
            literal(str(v))
            for v in (
                record.id,
                record.owner,
                record.corpus,
                record.created_at,
                record.data.model_dump_json(),
            )
        )
        result = self.query(
            "INSERT INTO public.corpus_ai_threads(id,owner,corpus,created_at,data) VALUES ("
            + values
            + ") ON CONFLICT(id) DO NOTHING RETURNING id;"
        )
        return bool(result.stdout.strip())


@pytest.fixture
def working(setup, archive, monkeypatch, database):
    job = jobs.ConversionJob(
        id=str(uuid4()),
        source_format="text",
        name="Private job",
        owner=setup.head.owner,
        status=jobs.JobStatus.SUCCEEDED,
        result_path=archive,
    )
    monkeypatch.setattr(jobs.job_manager, "get", lambda job_id: job if job_id == job.id else None)
    monkeypatch.setattr(jobs.job_manager, "materialize", lambda selected: archive)
    store = DraftThreads(database)
    monkeypatch.setattr(threads, "get_store", lambda: store)
    setup.job = job
    setup.source = archive
    return setup


def create(s):
    return s.client.post("/ai/drafts", json={"job_id": s.job.id})


def test_provision_apply_read_export_and_undo(working, database):
    s = working
    source_bytes = s.source.read_bytes()
    result = create(s)
    assert result.status_code == 200, result.text
    info = result.json()
    draft_id = info["id"]
    assert info["corpus"] == "draft:" + draft_id
    assert create(s).json() == info
    assert s.client.get("/ai/drafts").json()["drafts"] == [info]
    assert s.client.get(f"/ai/drafts/{draft_id}").json() == info
    scope = s.suggestion.scope.model_copy(
        update={"corpus": info["corpus"], "version": info["version"]}
    )
    response = s.client.post("/ai/threads", json={"scope": scope.model_dump(mode="json")})
    assert response.status_code == 200, response.text
    thread = response.json()
    proposal = s.suggestion.model_copy(
        update={"scope": scope, "base_version": info["version"]}, deep=True
    )
    suggestion = threads.save_suggestion(thread["id"], thread["sections"][0]["id"], proposal)
    applied = s.client.post(f"/ai/suggestions/{suggestion.id}/apply", json={})
    assert applied.status_code == 200, applied.text
    after = s.client.get(f"/ai/drafts/{draft_id}").json()
    assert after["revision"] != info["revision"]
    assert create(s).json() == after  # Never reset HEAD to the source job.
    node = s.client.get(f"/ai/drafts/{draft_id}/nodes/13")
    assert node.status_code == 200, node.text
    assert node.headers["cache-control"] == "private, no-store"
    assert node.json()["data"]["features"]["chapter"] == 3
    assert node.json()["draft"] == after
    for view in ("manifest", "index", "content", "sections", "versions"):
        response = s.client.get(f"/ai/drafts/{draft_id}/{view}")
        assert response.status_code == 200, (view, response.text)
        assert response.json()["draft"] == after
    exported = s.client.get(after["archive_url"])
    assert exported.status_code == 200
    assert exported.headers["x-draft-revision"] == after["revision"]
    assert exported.headers["cache-control"] == "private, no-store"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as packed:
        assert yaml.safe_load(packed.read("manifest.yml"))["version"] == after["version"]
        assert (
            json.loads(packed.read("ai-changes.json"))[-1]["operation_id"]
            == applied.json()["operation_id"]
        )
    undo = s.client.post(f"/ai/changes/{applied.json()['change']['change_id']}/undo")
    assert undo.status_code == 200, undo.text
    assert (
        s.client.get(f"/ai/drafts/{draft_id}/nodes/13").json()["data"]["features"]["chapter"] == 1
    )
    assert s.source.read_bytes() == source_bytes
    # No cache entries or local registrations can leak this per-call snapshot.
    assert not any("snapshot" in name for name in corpus_detail._local_archives)
    document = json.loads(
        database(f"SELECT to_jsonb(d) FROM public.corpus_documents d WHERE id='{draft_id}';").stdout
    )
    assert document["ai_private"] and document["job_id"] == s.job.id


def test_private_metadata_cannot_escape_legacy_policies(working, database):
    s = working
    info = create(s).json()
    legacy_id = str(uuid4())
    database(f"INSERT INTO public.corpus_documents(id) VALUES ('{legacy_id}');")
    for role in ("anon", "authenticated"):
        assert (
            database(
                f"SET ROLE {role}; SELECT count(*) FROM public.corpus_documents WHERE id='{info['id']}';"
            ).stdout.strip()
            == "0"
        )
        assert (
            database(
                f"SET ROLE {role}; SELECT count(*) FROM public.corpus_documents WHERE id='{legacy_id}';"
            ).stdout.strip()
            == "1"
        )
        database(f"SET ROLE {role}; DELETE FROM public.corpus_documents WHERE id='{info['id']}';")
        database(
            f"SET ROLE {role}; UPDATE public.corpus_documents SET ai_private=false WHERE id='{info['id']}';"
        )
        denied = database(
            f"SET ROLE {role}; INSERT INTO public.corpus_documents(id,ai_private) VALUES ('{uuid4()}',true);",
            check=False,
        )
        assert denied.returncode != 0
        assert (
            database(
                f"SELECT has_table_privilege('{role}','public.corpus_documents','TRUNCATE');"
            ).stdout.strip()
            == "f"
        )
    assert drafts.get(info["id"]).id == info["id"]


@pytest.mark.parametrize("state", ["foreign", "anonymous", "running", "failed", "missing"])
def test_unowned_or_incomplete_job_cannot_provision(working, monkeypatch, state):
    s = working
    if state == "foreign":
        s.job.owner = str(uuid4())
    elif state == "anonymous":
        s.job.owner = None
    elif state == "running":
        s.job.status = jobs.JobStatus.RUNNING
    elif state == "failed":
        s.job.status = jobs.JobStatus.FAILED
    else:
        monkeypatch.setattr(jobs.job_manager, "get", lambda _: None)
    monkeypatch.setattr(
        jobs.job_manager,
        "materialize",
        lambda _: pytest.fail("must authorize before materializing"),
    )
    response = create(s)
    assert response.status_code == (409 if state in ("running", "failed") else 404)
    assert s.client.get("/ai/drafts").json()["drafts"] == []


def test_foreign_draft_reads_and_export_are_denied(working):
    s = working
    info = create(s).json()
    headers = {"Authorization": "Bearer " + str(uuid4())}
    for suffix in ("", "/manifest", "/index", "/nodes/13", "/content", "/archive"):
        assert s.client.get(f"/ai/drafts/{info['id']}{suffix}", headers=headers).status_code == 404
    assert s.client.get("/ai/drafts", headers=headers).json()["drafts"] == []


def test_disabled_writes_preserve_explicit_draft_reads(working, monkeypatch):
    s = working
    info = create(s).json()
    monkeypatch.setattr(service.settings, "ai_mutations_enabled", False)
    assert create(s).status_code == 501
    assert s.client.get(info["archive_url"]).status_code == 200
    assert s.client.get(f"/ai/drafts/{info['id']}/nodes/13").status_code == 200
    scope = s.suggestion.scope.model_copy(
        update={"corpus": info["corpus"], "version": info["version"]}
    )
    assert (
        s.client.post("/ai/validate", json={"scope": scope.model_dump(mode="json")}).status_code
        == 200
    )
    monkeypatch.setattr(
        s.storage,
        "download",
        lambda *args: (_ for _ in ()).throw(JournalUnavailableError("secret")),
    )
    response = s.client.get(info["archive_url"])
    assert response.status_code == 503 and "secret" not in response.text


def test_concurrent_provisioning_has_one_binding(working, monkeypatch):
    s = working
    stage = s.storage.stage
    barrier = Barrier(2)

    def together(*args):
        result = stage(*args)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(s.storage, "stage", together)

    def attempt():
        token = current_owner.set(s.head.owner)
        try:
            return drafts.create(s.job.id)
        finally:
            current_owner.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [f.result(timeout=30) for f in futures]
    assert results[0] == results[1]
    assert len(drafts.list_drafts().drafts) == 1


@pytest.mark.asyncio
async def test_mcp_create_and_read(working):
    mcp = FastMCP("drafts")
    register_curation_tools(mcp)
    async with Client(mcp) as client:
        made = await client.call_tool("create_working_draft", {"job_id": working.job.id})
        listed = await client.call_tool("list_working_drafts", {})
        assert listed.data["drafts"] == [made.data]
        read = await client.call_tool(
            "read_working_draft", {"draft_id": made.data["id"], "view": "node", "node": 13}
        )
        assert read.data["data"]["features"]["chapter"] == 1


def test_upload_failure_leaves_no_document_binding(working, database, monkeypatch):
    s = working

    def unavailable(*args):
        raise JournalUnavailableError("secret storage URL")

    monkeypatch.setattr(s.storage, "stage", unavailable)
    response = create(s)
    assert response.status_code == 503 and "secret" not in response.text
    assert drafts.list_drafts().drafts == []
    assert (
        database(
            f"SELECT count(*) FROM public.corpus_documents WHERE job_id='{s.job.id}';"
        ).stdout.strip()
        == "0"
    )


def test_missing_draft_never_falls_back_to_legacy(working, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Explicit drafts must never use shared storage")

    monkeypatch.setattr(service.storage.corpus_storage, "download", forbidden)
    scope = working.suggestion.scope.model_copy(update={"corpus": "draft:" + str(uuid4())})
    response = working.client.post("/ai/validate", json={"scope": scope.model_dump(mode="json")})
    assert response.status_code == 404


def test_read_only_and_unsupported_sources_do_not_stage(working, monkeypatch):
    s = working
    monkeypatch.setattr(service.settings, "hf_read_only", True)
    assert create(s).status_code == 423
    monkeypatch.setattr(service.settings, "hf_read_only", False)
    # An ingest result without a .corpus archive must never become a draft.
    s.source.write_bytes(b"not a corpus archive")
    assert create(s).status_code == 422
    assert drafts.list_drafts().drafts == []


def test_private_reader_does_not_execute_archive_git_configuration(tmp_path, monkeypatch):
    archive = tmp_path / "with-git.corpus"
    with zipfile.ZipFile(archive, "w") as packed:
        packed.writestr("manifest.yml", "name: Mini\nversion: 1.0\n")
        packed.writestr(".git/config", "[log]\nshowSignature = true\n")

    def forbidden(*args, **kwargs):
        pytest.fail("Private readers must not run archive-supplied Git configuration")

    monkeypatch.setattr(corpus_detail.subprocess, "run", forbidden)
    result = corpus_detail.read_archive(archive, "versions")
    assert result["versions"][0]["label"] == "1.0"
