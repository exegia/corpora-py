"""Parse human-readable references like "Genesis 1:1" into section tuples.

Context-Fabric / Text-Fabric address text by `(book, chapter, verse)` tuples
passed to `T.nodeFromSection`. Users speak in strings — this module bridges
the two without the caller thinking about node IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_REFERENCE_RE = re.compile(
    r"""
    ^\s*
    (?P<book>[1-3]?\s?[A-Za-z][A-Za-z\s]*?)      # book name, optional leading 1/2/3
    \s+
    (?P<chapter>\d+)                              # chapter number
    (?:\s*[:.]\s*(?P<verse_start>\d+)             # optional :verse
       (?:\s*[-\u2013]\s*(?P<verse_end>\d+))?     # optional -end
    )?
    \s*$
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedReference:
    book: str
    chapter: int
    verse: int | None = None
    verse_end: int | None = None

    @property
    def is_verse(self) -> bool:
        return self.verse is not None and self.verse_end is None

    @property
    def is_range(self) -> bool:
        return self.verse_end is not None

    def section(self) -> tuple[str, int] | tuple[str, int, int]:
        if self.verse is None:
            return (self.book, self.chapter)
        return (self.book, self.chapter, self.verse)


def parse_reference(ref: str) -> ParsedReference:
    """Parse "Genesis 1:1", "Gen 1", "Gen 1:1-5" into a `ParsedReference`.

    Raises ValueError if the string can't be parsed.
    """
    match = _REFERENCE_RE.match(ref)
    if match is None:
        raise ValueError(f"could not parse reference: {ref!r}")

    book = re.sub(r"\s+", " ", match.group("book")).strip()
    chapter = int(match.group("chapter"))
    verse = int(match.group("verse_start")) if match.group("verse_start") else None
    verse_end = int(match.group("verse_end")) if match.group("verse_end") else None

    if verse_end is not None and verse is not None and verse_end < verse:
        raise ValueError(f"verse range is inverted in {ref!r}")

    return ParsedReference(
        book=book,
        chapter=chapter,
        verse=verse,
        verse_end=verse_end,
    )


def format_reference(book: str, chapter: int, verse: int | None = None) -> str:
    """Format a reference tuple back to a string."""
    if verse is None:
        return f"{book} {chapter}"
    return f"{book} {chapter}:{verse}"
