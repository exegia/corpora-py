"""Shared shapes for the `/ai` curation surface.

This module is the API contract for the reader's AI curation panel
(exegia/corpora-web spec `005-ai-assistant-panel`, tracking issue
exegia/corpora-web#101; backend issue exegia/corpora-py#214). It is
deliberately dependency-light — FastAPI/Pydantic only, no `admin` or
`corpora_mcp` imports — so the contract can be imported and tested without
loading a corpus, and so `tests/corpora_py/test_ai_contract.py` stays a
pure shape check.

Vocabulary notes:

- Scope *levels* are the UI's ladder (word → passage → section → document →
  corpus). Corpora name their own section types (`otext` section hierarchy:
  a Summa exposes quaestio/articulus, an EPUB book/chapter/paragraph), so a
  scope also carries the corpus's concrete ``node_type`` and display label —
  the level is for the panel's picker, the node type is the truth.
- Every write is version-bound and lands as a :class:`VersionHistoryEntry`.
  There is deliberately NO approval/review state in these shapes (that flow
  is deferred — see the spec's clarifications); when review arrives it
  layers onto the same entries rather than replacing them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class ScopeLevel(StrEnum):
    """The panel's scope ladder, smallest to largest."""

    word = "word"
    passage = "passage"  # a ¶/unit range inside one section
    section = "section"  # one section node (e.g. articulus, chapter)
    document = "document"  # one top-level document node (e.g. quaestio, book)
    corpus = "corpus"


class UnitRange(BaseModel):
    """Inclusive range of sibling units (paragraph-level nodes) in one section."""

    start: int = Field(description="First unit node id in the range")
    end: int = Field(description="Last unit node id in the range (inclusive)")

    @model_validator(mode="after")
    def _ordered(self) -> UnitRange:
        if self.end < self.start:
            raise ValueError("range end must be >= start")
        return self


class NodeScope(BaseModel):
    """A version-pinned reference to the corpus node(s) a thread works on.

    The scope is the smallest node containing the whole selection; a
    selection crossing a section boundary is clamped to whole sections by
    the client before it gets here (spec FR-002).
    """

    corpus: str = Field(description="Loaded corpus name (see /mcp list_corpora)")
    level: ScopeLevel
    node_id: int | None = Field(
        default=None,
        description="Anchor node id; None only for corpus-level scope",
    )
    node_type: str | None = Field(
        default=None,
        description='Corpus-specific node type of the anchor (e.g. "word", "paragraph", "chapter")',
    )
    label: str = Field(
        description='Display label as the chip shows it (e.g. "doctrinam · word · Q.1 a.1 ¶1")'
    )
    unit_range: UnitRange | None = Field(
        default=None, description="Present only for passage-level (multi-¶) scopes"
    )
    version: str = Field(
        description="Corpus working-version identifier the scope was captured at"
    )
    content_hash: str | None = Field(
        default=None,
        description="Hash of the scoped text at capture time; guards staleness on apply",
    )

    @model_validator(mode="after")
    def _corpus_level_has_no_node(self) -> NodeScope:
        if self.level is ScopeLevel.corpus:
            return self
        if self.node_id is None:
            raise ValueError(f"{self.level.value}-level scope requires node_id")
        return self


# ---------------------------------------------------------------------------
# Validation findings & suggestions
# ---------------------------------------------------------------------------


class Severity(StrEnum):
    error = "error"  # walker/loader breaks or returns wrong text
    warn = "warn"  # loads, but navigation/rendering degraded
    info = "info"  # legal and working; worth a deliberate decision


class Finding(BaseModel):
    """One Context-Fabric validation finding for a scoped node."""

    node_id: int
    node_type: str
    rule: str = Field(description='Rule code (e.g. "RC003", "TF025", "FEATURE_MISSING")')
    severity: Severity
    message: str = Field(description="What is wrong, naming the node")
    consequence: str = Field(
        description='What the editor observes (e.g. "¶2 renders 7 slots late")'
    )
    fixable: bool = Field(
        description="False for slot-level corruption — those need a walker re-run, not an edit"
    )
    unfixable_reason: str | None = None
    suggestion_id: str | None = Field(
        default=None, description="Set when a Suggestion was generated for this finding"
    )


class ValidateRequest(BaseModel):
    scope: NodeScope


class ValidateResponse(BaseModel):
    corpus: str
    version: str
    checked_nodes: int
    findings: list[Finding]


class SuggestionKind(StrEnum):
    annotation = "annotation"  # node feature value (lemma, case, POS, …)
    label = "label"  # section/heading label
    boundary = "boundary"  # unit boundary shift within existing slots
    formatting = "formatting"
    reference = "reference"  # citation/reference normalisation
    text = "text"  # slot text correction


class DiffRow(BaseModel):
    """One old→new pair; render with ins/del semantics + glyphs, never color alone."""

    field: str = Field(description='What changes (e.g. "case", "label", "text")')
    old: str | None
    new: str | None


class SuggestionStatus(StrEnum):
    pending = "pending"
    applied = "applied"
    rejected = "rejected"
    stale = "stale"


class Suggestion(BaseModel):
    """A version-bound suggested change. Generated content — never corpus text."""

    id: str
    scope: NodeScope
    kind: SuggestionKind
    target_node: int
    diff: list[DiffRow] = Field(min_length=1)
    rationale: str = Field(description="Generated rationale — the UI labels it as such")
    generated: Literal[True] = True
    base_version: str = Field(description="Corpus version the suggestion was made against")
    content_hash: str = Field(description="Hash of the target content at suggestion time")
    status: SuggestionStatus = SuggestionStatus.pending
    finding: Finding | None = None


# ---------------------------------------------------------------------------
# Apply / version history
# ---------------------------------------------------------------------------


class ApplyRequest(BaseModel):
    confirmation_token: str | None = Field(
        default=None,
        description=(
            "Required only for corpus-scope write commands (the corpora-web#100 "
            "confirmation gate); node-scope applies omit it"
        ),
    )


class VersionHistoryEntry(BaseModel):
    """The change-log record every applied change lands as, transactionally.

    This is the safety net that replaces approval for now: a change that is
    not recorded must not land. `resp` follows the TEI convention and always
    contains both the agent and the applying user.
    """

    change_id: str
    corpus: str
    version: str = Field(description="Working version the change is part of")
    node_id: int
    field: str
    previous_value: str | None
    new_value: str | None
    resp: list[str] = Field(
        description='Responsibility chain, e.g. ["#corpora-ai", "#<user-sub>"]',
        min_length=2,
    )
    applied_by: str = Field(description="Supabase JWT `sub` of the applying user")
    applied_at: datetime
    reverts: str | None = Field(
        default=None, description="change_id this entry reverts (set on undo entries)"
    )


class ApplyResponse(BaseModel):
    suggestion_id: str
    status: SuggestionStatus
    change: VersionHistoryEntry


class UndoResponse(BaseModel):
    reverted_change_id: str
    revert: VersionHistoryEntry


class ChangeLogResponse(BaseModel):
    corpus: str
    entries: list[VersionHistoryEntry]


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


class ThreadSection(BaseModel):
    """A fork created by an explicit re-scope; history is kept, never replaced."""

    id: str
    scope: NodeScope
    created_at: datetime


class Thread(BaseModel):
    id: str
    corpus: str
    pinned_scope: NodeScope = Field(
        description="The scope the thread follows — navigation never re-scopes it"
    )
    sections: list[ThreadSection]
    created_at: datetime


class ThreadCreateRequest(BaseModel):
    scope: NodeScope


class ThreadListResponse(BaseModel):
    threads: list[Thread]


# ---------------------------------------------------------------------------
# Chat (SSE)
# ---------------------------------------------------------------------------


class ChatMode(StrEnum):
    ask = "ask"
    fix = "fix"


class ChatRequest(BaseModel):
    thread_id: str | None = Field(
        default=None, description="Omit to start a new thread pinned to `scope`"
    )
    scope: NodeScope
    message: str = Field(min_length=1)
    mode: ChatMode = ChatMode.ask


class TokenEvent(BaseModel):
    """SSE `event: token` — a batch of streamed answer text."""

    type: Literal["token"] = "token"
    text: str


class ToolEvent(BaseModel):
    """SSE `event: tool` — an MCP tool call the agent made (validate, search, …)."""

    type: Literal["tool"] = "tool"
    tool: str
    status: Literal["started", "finished", "failed"]
    payload: dict[str, Any] | None = None


class SuggestionEvent(BaseModel):
    """SSE `event: suggestion` — a suggested fix for the panel to render as a card."""

    type: Literal["suggestion"] = "suggestion"
    suggestion: Suggestion


class DoneEvent(BaseModel):
    """SSE `event: done` — terminal; the stream closes after this."""

    type: Literal["done"] = "done"
    thread_id: str
    message_id: str


class ErrorInfo(BaseModel):
    """Uniform error/degradation shape (also the body of 4xx/5xx responses).

    `code` maps one-to-one onto the panel's degraded states:
    locked → 423, stale → 409, confirmation_required → 428,
    model_unavailable → 503, forbidden → 403.
    """

    code: Literal[
        "locked", "stale", "confirmation_required", "model_unavailable", "forbidden"
    ]
    reason: str = Field(description="Human-readable reason, shown verbatim in the panel")
    retryable: bool
    current_version: str | None = Field(
        default=None, description="Set for `stale`: the version that superseded the scope"
    )


class ErrorEvent(BaseModel):
    """SSE `event: error` — terminal; mirrors `ErrorInfo`."""

    type: Literal["error"] = "error"
    error: ErrorInfo


ChatEvent = TokenEvent | ToolEvent | SuggestionEvent | DoneEvent | ErrorEvent
"""Union of every SSE `data:` payload `/ai/chat` emits, discriminated by `type`."""


# ---------------------------------------------------------------------------
# Provider / gateway
# ---------------------------------------------------------------------------


class ProviderInfo(BaseModel):
    id: str = Field(description='Gateway provider slug (e.g. "anthropic", "openai")')
    label: str
    models: list[str] = Field(description="Suggested model ids; not exhaustive")


class ProvidersResponse(BaseModel):
    """What `POST /ai/chat` accepts in its provider headers.

    Model calls route through the Vercel AI Gateway (an AI-SDK-compatible,
    OpenAI-format endpoint). The caller supplies the provider and key
    per-request via headers — `X-AI-Provider`, `X-AI-Api-Key`, and optionally
    `X-AI-Model` — sourced from the user's Profile AI settings
    (exegia/corpora-web#54). Keys are request-scoped: never persisted, never
    logged. A missing/invalid key yields `ErrorInfo(code="model_unavailable")`.
    """

    gateway: Literal["vercel-ai-gateway"] = "vercel-ai-gateway"
    providers: list[ProviderInfo]
