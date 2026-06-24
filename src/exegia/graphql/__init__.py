"""Strawberry GraphQL layer over Context-Fabric corpora."""

from .corpus import CorpusHandle, CorpusRegistry, registry
from .references import ParsedReference, parse_reference
from .schema import Query, schema
from .types import (
    Book,
    Chapter,
    Clause,
    Corpus,
    Phrase,
    SearchMatch,
    Verse,
    Word,
    WordFilter,
)

__all__ = [
    "Book",
    "Chapter",
    "Clause",
    "Corpus",
    "CorpusHandle",
    "CorpusRegistry",
    "ParsedReference",
    "Phrase",
    "Query",
    "SearchMatch",
    "Verse",
    "Word",
    "WordFilter",
    "parse_reference",
    "registry",
    "schema",
]


def main() -> None:
    """Print the SDL representation of the schema. Handy for `uv run graphql`."""
    print(schema.as_str())
