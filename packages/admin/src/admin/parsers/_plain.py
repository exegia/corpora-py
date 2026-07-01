"""
Plain-text parser — converts a raw text file into the shared Document/Unit
schema. Paragraphs (blocks separated by a blank line) become top-level
`Unit`s, which keeps the amount of text held per unit small enough for
asynchronous conversion of very large plain-text corpora.
"""

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

from .schema import DocumentMetadata, Parser, SourceFormat, Unit, read_source_bytes, tokenize


def _load_text(source: str) -> str:
    return read_source_bytes(source).decode("utf-8")


def _title_from_source(source: str) -> str | None:
    if source.startswith(("http://", "https://")):
        name = Path(urlparse(source).path).stem
        return name or None
    return Path(source).stem or None


class PlainTextParser(Parser):
    format = SourceFormat.PLAIN

    def parse_metadata(self, source: str) -> DocumentMetadata:
        return DocumentMetadata(
            source_format=SourceFormat.PLAIN,
            title=_title_from_source(source),
        )

    def iter_units(self, source: str) -> Iterator[Unit]:
        text = _load_text(source)
        for index, paragraph in enumerate(text.split("\n\n")):
            if not paragraph.strip():
                continue
            yield Unit(type="paragraph", id=str(index), tokens=tokenize(paragraph))
