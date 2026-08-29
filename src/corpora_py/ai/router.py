"""FastAPI router for the `/ai` curation surface — contract stub.

Every endpoint here is part of the frozen contract for the reader's AI
curation panel (exegia/corpora-web spec `005-ai-assistant-panel`;
implementation issue exegia/corpora-py#214). The write/chat handlers return
**501 Not Implemented** on purpose: the point of this router, right now, is
the OpenAPI document — request/response models, status codes, and SSE event
shapes — so exegia/corpora-web#108 can build and unit-test against mocks
while the real handlers land behind the same signatures.

Contract rules the implementation must keep (spec FR-008/FR-009):

- Apply writes immediately to the working version — there is no approval
  step — but the write MUST be transactional with its
  :class:`~corpora_py.ai.schemas.VersionHistoryEntry`; a change that is not
  recorded must not land.
- Published corpora are locked: writes answer 423 with
  ``ErrorInfo(code="locked")``. Stale suggestions answer 409. Corpus-scope
  write commands without a confirmation token answer 428 (corpora-web#100).
- Model calls route through the Vercel AI Gateway with a per-request
  provider + API key supplied in headers (see `GET /ai/providers`); keys are
  never persisted or logged.

Like `/validate`, everything here is gated by the combined app's
`AuthMiddleware` simply by being mounted on it; the agent additionally must
never exceed the caller's own permissions.

SSE contract for `POST /ai/chat` (``text/event-stream``): each frame is
``event: <type>`` + ``data: <json>`` where ``<json>`` is one of the
``*Event`` models in `schemas.py` (`token`, `tool`, `suggestion`, `done`,
`error`). `done` and `error` are terminal.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from .schemas import (
    ApplyRequest,
    ApplyResponse,
    ChangeLogResponse,
    ChatEvent,
    ChatRequest,
    ErrorInfo,
    ProviderInfo,
    ProvidersResponse,
    Thread,
    ThreadCreateRequest,
    ThreadListResponse,
    UndoResponse,
    ValidateRequest,
    ValidateResponse,
)

router = APIRouter(prefix="/ai", tags=["AI Curation"])

_NOT_IMPLEMENTED = (
    "Contract stub — implementation tracked by exegia/corpora-py#214. "
    "Shapes in this endpoint's OpenAPI entry are frozen; build mocks against them."
)

# Error responses shared by every write/chat endpoint, so the OpenAPI document
# carries the degradation shapes the panel renders (spec FR-013).
_ERROR_RESPONSES: dict[int | str, dict] = {
    403: {"model": ErrorInfo, "description": "Caller lacks rights on this corpus"},
    423: {"model": ErrorInfo, "description": "Corpus is published and locked"},
    503: {"model": ErrorInfo, "description": "Model/provider unavailable (retryable)"},
}


def _not_implemented() -> HTTPException:
    return HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)


@router.get("/providers", response_model=ProvidersResponse)
async def providers() -> ProvidersResponse:
    """Providers accepted by the chat endpoint's `X-AI-Provider` header.

    The only endpoint of this router implemented ahead of #214: the web app
    needs the list (and the header contract documented on the response
    model) to build the Profile AI settings hand-off before the agent loop
    exists. Static by design — the gateway routes whatever provider/model
    the caller names; this list is UI guidance, not an allowlist.
    """
    return ProvidersResponse(
        providers=[
            ProviderInfo(
                id="anthropic",
                label="Anthropic",
                models=["claude-sonnet-4-5", "claude-haiku-4-5"],
            ),
            ProviderInfo(id="openai", label="OpenAI", models=["gpt-5.2", "gpt-5.2-mini"]),
            ProviderInfo(
                id="google", label="Google", models=["gemini-3-pro", "gemini-3-flash"]
            ),
        ]
    )


@router.post(
    "/chat",
    responses={
        200: {
            # `model` registers the ChatEvent union (and everything it pulls
            # in, e.g. Suggestion) in the OpenAPI components even though the
            # wire format is SSE, not a JSON body -- each `data:` line is one
            # ChatEvent, discriminated by its `type` field.
            "model": ChatEvent,  # type: ignore[dict-item]
            "content": {"text/event-stream": {}},
            "description": (
                "SSE stream of token / tool / suggestion events, terminated by "
                "done or error; each `data:` payload is one ChatEvent"
            ),
        },
        **_ERROR_RESPONSES,
    },
)
async def chat(
    request: ChatRequest,
    x_ai_provider: str = Header(description="Gateway provider slug (see /ai/providers)"),
    x_ai_api_key: str = Header(description="Caller's provider API key; request-scoped"),
    x_ai_model: str | None = Header(default=None, description="Optional model override"),
) -> None:
    """One chat turn, streamed over SSE. Cancelling the request stops generation."""
    raise _not_implemented()


@router.post("/validate", response_model=ValidateResponse, responses=_ERROR_RESPONSES)
async def validate_scope(request: ValidateRequest) -> ValidateResponse:
    """Run Context-Fabric validation for a scope; findings carry node ids + consequences."""
    raise _not_implemented()


@router.post(
    "/suggestions/{suggestion_id}/apply",
    response_model=ApplyResponse,
    responses={
        409: {"model": ErrorInfo, "description": "Suggestion is stale (version/hash drift)"},
        428: {
            "model": ErrorInfo,
            "description": "Corpus-scope write without a confirmation token (corpora-web#100)",
        },
        **_ERROR_RESPONSES,
    },
)
async def apply_suggestion(suggestion_id: str, request: ApplyRequest) -> ApplyResponse:
    """Apply a suggested fix to the working version — transactional with its history entry."""
    raise _not_implemented()


@router.post("/suggestions/{suggestion_id}/reject", status_code=204)
async def reject_suggestion(suggestion_id: str) -> None:
    """Discard a suggestion; nothing is written, the thread records the rejection."""
    raise _not_implemented()


@router.post(
    "/changes/{change_id}/undo", response_model=UndoResponse, responses=_ERROR_RESPONSES
)
async def undo_change(change_id: str) -> UndoResponse:
    """Revert an applied change; the revert is itself a version-history entry."""
    raise _not_implemented()


@router.get("/changes", response_model=ChangeLogResponse)
async def change_log(corpus: str, node_id: int | None = None) -> ChangeLogResponse:
    """Version-history entries for a corpus (optionally one node) — feeds reader marks."""
    raise _not_implemented()


@router.post("/threads", response_model=Thread)
async def create_thread(request: ThreadCreateRequest) -> Thread:
    """Create a thread pinned to a scope. Navigation never re-scopes it (spec FR-012)."""
    raise _not_implemented()


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads(corpus: str) -> ThreadListResponse:
    """Threads for a corpus, newest first."""
    raise _not_implemented()


@router.get("/threads/{thread_id}", response_model=Thread)
async def get_thread(thread_id: str) -> Thread:
    """One thread with its sections (explicit re-scope forks)."""
    raise _not_implemented()
