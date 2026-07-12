"""Fixtures for exercising the /convert HTTP surface without real conversions."""

import pytest
from admin.services import api as api_module
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
    return mgr


@pytest.fixture
def claims_holder():
    return {"claims": None}


@pytest.fixture
def client(manager, claims_holder, tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "_WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
    app = FastAPI()
    app.include_router(api_module.router)
    app.include_router(ws_module.router)
    app.add_middleware(ClaimsMiddleware, claims_holder=claims_holder)
    return TestClient(app)
