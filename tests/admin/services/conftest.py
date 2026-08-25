"""Fixtures for exercising the /convert HTTP surface without real conversions."""

import pytest
from admin.services import api as api_module
from admin.services import ingest_api as ingest_module
from admin.services import jobs as jobs_mod
from admin.services import websocket as ws_module
from admin.services.jobs import JobManager
from fastapi import FastAPI
from fastapi.testclient import TestClient


class DeferredExecutor:
    """Holds submitted work so no real conversion pipeline ever runs."""

    def __init__(self):
        self.pending = []

    def submit(self, fn, *args):
        self.pending.append((fn, args))

    def run_all(self):
        for fn, args in self.pending:
            fn(*args)
        self.pending.clear()

    def shutdown(self, **kwargs):
        pass


class ClaimsMiddleware:
    """Injects claims into scope['state'] the way AuthMiddleware would."""

    def __init__(self, app, claims_holder):
        self.app = app
        self.claims_holder = claims_holder

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and self.claims_holder["claims"] is not None:
            scope.setdefault("state", {})["user"] = self.claims_holder["claims"]
        await self.app(scope, receive, send)


@pytest.fixture
def manager(monkeypatch):
    mgr = JobManager(max_workers=1)
    mgr._executor.shutdown(wait=False, cancel_futures=True)
    mgr._executor = DeferredExecutor()
    monkeypatch.setattr(api_module, "job_manager", mgr)
    monkeypatch.setattr(ws_module, "job_manager", mgr)
    monkeypatch.setattr(ingest_module, "job_manager", mgr)
    monkeypatch.setattr(jobs_mod, "job_manager", mgr)
    return mgr


@pytest.fixture(autouse=True)
def _stub_corpus_validation(monkeypatch):
    """Make post-conversion validation (issue #177) always pass by default.

    These tests fake `convert_to_corpus` with paths that never exist on
    disk, so running the real `validate_corpus_archive` would fail every
    job. Patched at the `corpora_mcp.validate` module attribute (the gate
    imports it lazily at call time), so gate tests can re-patch the same
    seam with their own summaries.
    """
    import corpora_mcp.validate as validate_module

    class _AlwaysValid:
        def summary(self):
            return {
                "corpus": "",
                "valid": True,
                "stats": {},
                "reasons": [],
                "checks": [],
            }

    monkeypatch.setattr(
        validate_module,
        "validate_corpus_archive",
        lambda archive, corpus_name=None: _AlwaysValid(),
    )


@pytest.fixture
def claims_holder():
    return {"claims": None}


@pytest.fixture
def client(manager, claims_holder, tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "_WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
    # ingest_api binds the same roots by `from .api import ...`, so its module
    # globals need patching separately from api_module's.
    monkeypatch.setattr(ingest_module, "_WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(ingest_module, "_RESULTS_ROOT", tmp_path / "results")
    app = FastAPI()
    app.include_router(api_module.router)
    app.include_router(ws_module.router)
    app.include_router(ingest_module.router)
    app.add_middleware(ClaimsMiddleware, claims_holder=claims_holder)
    return TestClient(app)
