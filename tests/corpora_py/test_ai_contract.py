"""Contract tests for the `/ai` curation surface (`corpora_py.ai`).

The router is a contract-first stub (exegia/corpora-py#214): what these
tests freeze is the *shape* — paths, models, status codes, SSE event
schemas — that exegia/corpora-web#108 builds its mocks against. Auth gating
is the combined app's `AuthMiddleware` concern (see
`test_auth_middleware.py`), so the router is mounted bare here, mirroring
`test_validation_api.py`.

If a change here is intentional, it is a contract change: coordinate with
corpora-web#108 before relaxing an assertion.
"""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from corpora_py.ai import router
from corpora_py.ai.schemas import (
    ChatRequest,
    DoneEvent,
    ErrorEvent,
    ErrorInfo,
    Finding,
    NodeScope,
    ScopeLevel,
    Suggestion,
    SuggestionEvent,
    TokenEvent,
    ToolEvent,
    UnitRange,
    VersionHistoryEntry,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _scope(**overrides: object) -> dict:
    base: dict = {
        "corpus": "PrimaPars",
        "level": "passage",
        "node_id": 51203,
        "node_type": "paragraph",
        "label": "a.1 ¶1–¶2 · passage",
        "unit_range": {"start": 51203, "end": 51204},
        "version": "v2.15",
        "content_hash": "sha256:abc",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# The OpenAPI document is the deliverable — freeze paths and schema names.
# ---------------------------------------------------------------------------


def test_openapi_freezes_contract_paths(client):
    paths = client.app.openapi()["paths"]
    expected = {
        "/ai/providers",
        "/ai/chat",
        "/ai/validate",
        "/ai/suggestions/{suggestion_id}/apply",
        "/ai/suggestions/{suggestion_id}/reject",
        "/ai/changes/{change_id}/undo",
        "/ai/changes",
        "/ai/threads",
        "/ai/threads/{thread_id}",
    }
    assert expected <= set(paths)


def test_openapi_carries_contract_schemas(client):
    schemas = client.app.openapi()["components"]["schemas"]
    for name in (
        "NodeScope",
        "Finding",
        "Suggestion",
        "DiffRow",
        "VersionHistoryEntry",
        "ApplyResponse",
        "UndoResponse",
        "Thread",
        "ErrorInfo",
        "ProvidersResponse",
    ):
        assert name in schemas, f"contract schema {name} missing from OpenAPI"


def test_apply_documents_degradation_status_codes(client):
    responses = client.app.openapi()["paths"]["/ai/suggestions/{suggestion_id}/apply"][
        "post"
    ]["responses"]
    # 409 stale, 423 locked, 428 confirmation gate, 503 model unavailable
    assert {"409", "423", "428", "503"} <= set(responses)


def test_chat_requires_provider_headers(client):
    """The gateway contract: provider + api key arrive per-request in headers."""
    resp = client.post("/ai/chat", json={"scope": _scope(), "message": "hi"})
    assert resp.status_code == 422
    missing = {err["loc"][-1] for err in resp.json()["detail"]}
    assert {"x-ai-provider", "x-ai-api-key"} <= missing


# ---------------------------------------------------------------------------
# Stub behavior: writes are honestly unimplemented, providers is live.
# ---------------------------------------------------------------------------


def test_stub_endpoints_return_501(client):
    headers = {"X-AI-Provider": "anthropic", "X-AI-Api-Key": "k"}
    calls = [
        ("post", "/ai/chat", {"json": {"scope": _scope(), "message": "hi"}, "headers": headers}),
        ("post", "/ai/validate", {"json": {"scope": _scope()}}),
        ("post", "/ai/suggestions/s1/apply", {"json": {}}),
        ("post", "/ai/suggestions/s1/reject", {}),
        ("post", "/ai/changes/c1/undo", {}),
        ("get", "/ai/changes", {"params": {"corpus": "PrimaPars"}}),
        ("post", "/ai/threads", {"json": {"scope": _scope()}}),
        ("get", "/ai/threads", {"params": {"corpus": "PrimaPars"}}),
        ("get", "/ai/threads/t1", {}),
    ]
    for method, path, kwargs in calls:
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code == 501, f"{method.upper()} {path} -> {resp.status_code}"
        assert "corpora-py#214" in resp.json()["detail"]


def test_providers_endpoint_is_live(client):
    resp = client.get("/ai/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gateway"] == "vercel-ai-gateway"
    assert {p["id"] for p in body["providers"]} >= {"anthropic", "openai"}


# ---------------------------------------------------------------------------
# Scope shape rules (spec FR-002/FR-003).
# ---------------------------------------------------------------------------


def test_scope_levels_are_exactly_the_ladder():
    assert [level.value for level in ScopeLevel] == [
        "word",
        "passage",
        "section",
        "document",
        "corpus",
    ]


def test_node_scope_requires_node_id_below_corpus_level():
    with pytest.raises(ValidationError, match="requires node_id"):
        NodeScope(
            corpus="PrimaPars",
            level=ScopeLevel.word,
            label="doctrinam · word",
            version="v2.15",
        )


def test_corpus_scope_needs_no_node_id():
    scope = NodeScope(
        corpus="PrimaPars",
        level=ScopeLevel.corpus,
        label="Prima Pars · corpus · 119 qq.",
        version="v2.15",
    )
    assert scope.node_id is None


def test_unit_range_must_be_ordered():
    with pytest.raises(ValidationError):
        UnitRange(start=10, end=9)


# ---------------------------------------------------------------------------
# Write-path shapes: the no-approval model leans entirely on these.
# ---------------------------------------------------------------------------


def test_version_history_entry_requires_dual_resp():
    """Every change carries BOTH the agent and the applying user (FR-009)."""
    entry = dict(
        change_id="c1",
        corpus="PrimaPars",
        version="v2.15",
        node_id=51219,
        field="case",
        previous_value="NOM",
        new_value="ACC",
        applied_by="user-sub",
        applied_at=datetime.now(tz=UTC),
    )
    with pytest.raises(ValidationError):
        VersionHistoryEntry(**entry, resp=["#corpora-ai"])
    ok = VersionHistoryEntry(**entry, resp=["#corpora-ai", "#user-sub"])
    assert ok.reverts is None


def test_suggestion_is_always_marked_generated():
    suggestion = Suggestion(
        id="s1",
        scope=NodeScope(**_scope()),
        kind="annotation",
        target_node=51219,
        diff=[{"field": "case", "old": "NOM", "new": "ACC"}],
        rationale="-am marks accusative singular",
        base_version="v2.15",
        content_hash="sha256:abc",
    )
    assert suggestion.generated is True
    with pytest.raises(ValidationError):
        Suggestion(**{**suggestion.model_dump(), "generated": False})


def test_finding_carries_consequence_and_fixability():
    finding = Finding(
        node_id=51203,
        node_type="paragraph",
        rule="RC003",
        severity="warn",
        message="boundary starts 7 slots late",
        consequence="¶2 renders with the wrong opening words",
        fixable=True,
    )
    assert finding.suggestion_id is None


# ---------------------------------------------------------------------------
# SSE event shapes: what a mocked stream must emit.
# ---------------------------------------------------------------------------


def test_sse_event_types_are_discriminated():
    events = [
        TokenEvent(text="Running validation…"),
        ToolEvent(tool="validate_node", status="started"),
        SuggestionEvent(
            suggestion=Suggestion(
                id="s1",
                scope=NodeScope(**_scope()),
                kind="annotation",
                target_node=51219,
                diff=[{"field": "case", "old": "NOM", "new": "ACC"}],
                rationale="r",
                base_version="v2.15",
                content_hash="h",
            )
        ),
        DoneEvent(thread_id="t1", message_id="m1"),
        ErrorEvent(
            error=ErrorInfo(
                code="model_unavailable", reason="no API key configured", retryable=True
            )
        ),
    ]
    assert [e.type for e in events] == ["token", "tool", "suggestion", "done", "error"]


def test_chat_request_defaults_to_ask_mode():
    request = ChatRequest(scope=NodeScope(**_scope()), message="hi")
    assert request.mode.value == "ask"
    assert request.thread_id is None
