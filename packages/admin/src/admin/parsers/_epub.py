"""
EPUB parser — converts an EPUB ebook into the shared Document/Unit schema.

Each spine document (chapter/page) becomes its own top-level `Unit`, which is
the natural point at which a large EPUB (a novel, a multi-volume work) can be
split for asynchronous, per-chapter conversion. Chapter content is HTML, so
it's walked with the same tree walker `_html.py` uses.
"""

import io
from collections.abc import Iterator

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from ._html import top_level_units
from .schema import DocumentMetadata, Parser, SourceFormat, Unit, read_source_bytes, tokenize


def _load_book(source: str) -> epub.EpubBook:
    return epub.read_epub(io.BytesIO(read_source_bytes(source)))


def _dc(book: epub.EpubBook, name: str) -> list[str]:
    """Read every value of a Dublin Core metadata field (e.g. "creator")."""
    return [value for value, _ in book.get_metadata("DC", name)]


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


class EpubParser(Parser):
    format = SourceFormat.EPUB

    def parse_metadata(self, source: str) -> DocumentMetadata:
        book = _load_book(source)
        return DocumentMetadata(
            source_format=SourceFormat.EPUB,
            title=_first(_dc(book, "title")),
            creators=_dc(book, "creator"),
            language=_first(_dc(book, "language")),
            publisher=_first(_dc(book, "publisher")),
            date=_first(_dc(book, "date")),
            description=_first(_dc(book, "description")),
            identifier=_first(_dc(book, "identifier")),
            rights=_first(_dc(book, "rights")),
            subjects=_dc(book, "subject"),
        )

    def iter_units(self, source: str) -> Iterator[Unit]:
        book = _load_book(source)
        for item in book.get_items():
            if item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            soup = BeautifulSoup(item.get_content(), "html.parser")
            body = soup.find("body") or soup
            children = top_level_units(body)

            yield Unit(
                type="chapter",
                id=item.get_id(),
                attrs={"name": item.get_name()},
                children=children,
                tokens=tokenize(body.get_text()) if not children else [],
            )
