"""
PDF parser — converts a PDF into the shared Document/Unit schema.

Each page becomes its own top-level `Unit`, which is the natural point at
which a large PDF (a scanned book, a bible) can be split for asynchronous,
per-page conversion.
"""

import io
from collections.abc import Iterator

from pypdf import PdfReader

from .schema import DocumentMetadata, Parser, SourceFormat, Unit, read_source_bytes, tokenize


def _load(source: str) -> PdfReader:
    return PdfReader(io.BytesIO(read_source_bytes(source)))


class PdfParser(Parser):
    format = SourceFormat.PDF

    def parse_metadata(self, source: str) -> DocumentMetadata:
        reader = _load(source)
        info = reader.metadata

        extra: dict[str, str] = {}
        if info and info.producer:
            extra["producer"] = info.producer
        if info and info.creator:
            extra["creator"] = info.creator

        return DocumentMetadata(
            source_format=SourceFormat.PDF,
            title=info.title if info else None,
            creators=[info.author] if info and info.author else [],
            date=info.creation_date.isoformat() if info and info.creation_date else None,
            subjects=[info.subject] if info and info.subject else [],
            extra=extra,
        )

    def iter_units(self, source: str) -> Iterator[Unit]:
        reader = _load(source)
        for index, page in enumerate(reader.pages):
            yield Unit(
                type="page",
                id=str(index),
                attrs={"page_number": str(index + 1)},
                tokens=tokenize(page.extract_text()),
            )
