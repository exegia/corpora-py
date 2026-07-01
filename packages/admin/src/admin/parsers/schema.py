"""
Format-agnostic document schema shared by every parser in this package.

Every `_{mime_type}.py` parser converts its source format into this same
shape: a `Document` (metadata + a tree of `Unit`s, each `Unit` holding either
child `Unit`s or leaf `Token`s). The tree mirrors how a Text-Fabric walker
builds a corpus (`tf.convert.walker.CV`): a `Unit` maps to `cv.node(type)`,
its `children` are nodes created while it stays the active embedder, and its
`tokens` map to `cv.slot()` calls carrying `text`/`after` features.

Keeping one recursive `Unit` type (instead of separate section/paragraph/
table types) is what makes the schema format-agnostic: a book's chapters, an
XML tree, a TEI `<div>` hierarchy, and a PDF's pages all fit the same shape.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field

# ── Enums ─────────────────────────────────────────────────────────────────────


class SourceFormat(StrEnum):
    EPUB = "epub"
    HTML = "html"
    XML = "xml"
    TEI = "tei"
    PDF = "pdf"
    PLAIN = "plain"


# ── Schema ────────────────────────────────────────────────────────────────────


class DocumentMetadata(BaseModel):
    """Dublin-Core-ish metadata, common enough to exist across all formats."""

    source_format: SourceFormat
    title: str | None = None
    creators: list[str] = Field(default_factory=list)
    language: str | None = None
    publisher: str | None = None
    date: str | None = None
    description: str | None = None
    identifier: str | None = None
    rights: str | None = None
    subjects: list[str] = Field(default_factory=list)
    # Format-specific fields that don't fit the common ones above (e.g. PDF
    # producer, TEI edition statement) are kept here rather than growing the
    # schema per format.
    extra: dict[str, str] = Field(default_factory=dict)


class Token(BaseModel):
    """A single slot: the atomic text unit (typically a word)."""

    text: str
    # Whitespace/punctuation following this token, up to the next token.
    # Mirrors the "after" feature convention used by Text-Fabric walkers.
    after: str = ""


class Unit(BaseModel):
    """
    A single node in the document tree: a chapter, page, div, paragraph,
    table row, verse — anything that either contains other `Unit`s or holds
    text as `Token`s.

    `type` is a free-form label (e.g. "chapter", "p", "table", "verse") kept
    as a string rather than an enum, since each format has its own vocabulary
    and new ones must be addable without touching this schema.
    """

    type: str
    id: str | None = None
    label: str | None = None
    attrs: dict[str, str] = Field(default_factory=dict)
    tokens: list[Token] = Field(default_factory=list)
    children: list[Unit] = Field(default_factory=list)


Unit.model_rebuild()


class Document(BaseModel):
    metadata: DocumentMetadata
    units: list[Unit] = Field(default_factory=list)


# ── Shared source loading ────────────────────────────────────────────────────


def read_source_bytes(source: str) -> bytes:
    """Read `source` (a local file path or an http(s) URL) into memory."""
    if source.startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(source) as response:  # noqa: S310
            data: bytes = response.read()
            return data
    with open(source, "rb") as fh:
        return fh.read()


# ── Shared tokenizer ──────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"\S+")


def tokenize(text: str | None) -> list[Token]:
    """
    Split text into `Token`s, capturing the whitespace/punctuation between
    words as each token's `after` so the original spacing can be
    reconstructed. Shared by every parser so tokenization stays consistent.
    """
    if not text:
        return []
    matches = list(_WORD_RE.finditer(text))
    tokens: list[Token] = []
    for i, match in enumerate(matches):
        end = match.end()
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        tokens.append(Token(text=match.group(), after=text[end:next_start]))
    return tokens


# ── Base parser ───────────────────────────────────────────────────────────────


class Parser(ABC):
    """
    Common contract for every format-specific parser.

    `iter_units()` yields one top-level `Unit` at a time (a chapter, a page,
    a book) instead of returning a fully built `Document`, so a caller
    converting a large source (a book, a bible) can process/convert each
    unit as it arrives instead of holding the whole tree in memory.
    """

    format: ClassVar[SourceFormat]

    @abstractmethod
    def parse_metadata(self, source: str) -> DocumentMetadata:
        """Read just the metadata of `source` (a file path or URL)."""

    @abstractmethod
    def iter_units(self, source: str) -> Iterator[Unit]:
        """Yield top-level `Unit`s of `source` one at a time."""

    def parse(self, source: str) -> Document:
        """Parse `source` fully into a `Document`. Convenience wrapper around
        `parse_metadata`/`iter_units` for callers that don't need streaming."""
        return Document(
            metadata=self.parse_metadata(source),
            units=list(self.iter_units(source)),
        )
