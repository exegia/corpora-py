"""FastAPI router for the `/ai` curation surface.

Every endpoint here is part of the frozen contract for the reader's AI
curation panel (exegia/corpora-web spec `005-ai-assistant-panel`;
implementation issue exegia/corpora-py#214). The write/chat handlers return
**501 Not Implemented** while those slices are pending. Providers and scoped
validation, owned conversations, and suggestion rejection are live. The OpenAPI document preserves the request/response
models, status codes, and SSE event shapes used by corpora-web#108.

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

import asyncio

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from .schemas import (
    ApplyRequest,
    ApplyResponse,
    ChangeLogResponse,
    ChatEvent,
    ChatRequest,
    ErrorInfo,
    MessageCreateRequest,
    MessageListResponse,
    ProviderInfo,
    ProvidersResponse,
    SuggestionListResponse,
    SuggestionStatus,
    Thread,
    ThreadCreateRequest,
    ThreadListResponse,
    ThreadMessage,
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

    Implemented ahead of the chat portion of #214: the web app
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
            ProviderInfo(id="google", label="Google", models=["gemini-3-pro", "gemini-3-flash"]),
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


@router.post(
    "/validate",
    response_model=ValidateResponse,
    responses={
        **_ERROR_RESPONSES,
        404: {
            "model": dict[str, str],
            "description": "Corpus not found or not owned by the caller",
        },
        409: {
            "model": ErrorInfo | dict[str, str],
            "description": "Stale scope, or conversion not ready",
        },
        422: {"description": "Invalid scope or unreadable corpus"},
        503: {"model": dict[str, str], "description": "Corpus storage is unavailable"},
    },
)
async def validate_scope(request: ValidateRequest) -> ValidateResponse | JSONResponse:
    """Run Context-Fabric validation for a scope; findings carry node ids + consequences."""
    from . import service

    try:
        return await asyncio.to_thread(service.validate_scope, request.scope)
    except service.CurationError as exc:
        return JSONResponse(status_code=exc.status, content=exc.body)


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


@router.post("/suggestions/{suggestion_id}/reject", status_code=204, response_model=None)
async def reject_suggestion(suggestion_id: str) -> JSONResponse | None:
    """Discard a suggestion; nothing is written, the thread records the rejection."""
    from .threads import transition_suggestion

    result = await _thread_call(transition_suggestion, suggestion_id, SuggestionStatus.rejected)
    if isinstance(result, JSONResponse):
        return result
    return None


@router.post("/changes/{change_id}/undo", response_model=UndoResponse, responses=_ERROR_RESPONSES)
async def undo_change(change_id: str) -> UndoResponse:
    """Revert an applied change; the revert is itself a version-history entry."""
    raise _not_implemented()


@router.get("/changes", response_model=ChangeLogResponse)
async def change_log(corpus: str, node_id: int | None = None) -> ChangeLogResponse:
    """Version-history entries for a corpus (optionally one node) — feeds reader marks."""
    raise _not_implemented()


@router.post("/threads", response_model=Thread)
async def create_thread(
    request: ThreadCreateRequest, idempotency_key: str | None = Header(default=None)
) -> Thread | JSONResponse:
    """Create a thread pinned to a scope. Navigation never re-scopes it (spec FR-012)."""
    from .threads import create_thread as create

    return await _thread_call(create, request.scope, idempotency_key)


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads(
    corpus: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
) -> ThreadListResponse | JSONResponse:
    """Threads for a corpus, newest first."""
    from .threads import list_threads as list_owned

    return await _thread_call(list_owned, corpus, limit, cursor)


@router.get("/threads/{thread_id}", response_model=Thread)
async def get_thread(thread_id: str) -> Thread | JSONResponse:
    """One thread with its sections (explicit re-scope forks)."""
    from .threads import get_thread as get_owned

    return await _thread_call(get_owned, thread_id)


async def _thread_call(fn, *args):
    from .service import CurationError
    from .thread_store import ThreadStoreError

    try:
        return await asyncio.to_thread(fn, *args)
    except CurationError as exc:
        return JSONResponse(status_code=exc.status, content=exc.body)
    except ThreadStoreError:
        return JSONResponse(status_code=503, content={"detail": "Conversation storage unavailable"})


@router.post("/threads/{thread_id}/sections", response_model=Thread)
async def fork_thread_section(
    thread_id: str, request: ThreadCreateRequest, idempotency_key: str | None = Header(default=None)
) -> Thread | JSONResponse:
    """Explicitly re-scope into a new section without changing the original pin."""
    from .threads import fork_section

    return await _thread_call(fork_section, thread_id, request.scope, idempotency_key)


@router.post("/threads/{thread_id}/messages", response_model=ThreadMessage)
async def create_thread_message(
    thread_id: str,
    request: MessageCreateRequest,
    idempotency_key: str | None = Header(default=None),
) -> ThreadMessage | JSONResponse:
    from .threads import append_message

    return await _thread_call(
        append_message, thread_id, request.section_id, request.content, idempotency_key
    )


@router.get("/threads/{thread_id}/messages", response_model=MessageListResponse)
async def list_thread_messages(
    thread_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse | JSONResponse:
    from .threads import list_messages

    return await _thread_call(list_messages, thread_id, limit, offset)


@router.get("/threads/{thread_id}/suggestions", response_model=SuggestionListResponse)
async def list_thread_suggestions(
    thread_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SuggestionListResponse | JSONResponse:
    from .threads import list_suggestions

    return await _thread_call(list_suggestions, thread_id, limit, offset)
