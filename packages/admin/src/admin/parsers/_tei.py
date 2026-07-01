"""
TEI (Text Encoding Initiative) XML parser — converts a TEI document into the
shared Document/Unit schema.

TEI is XML, so the document body is walked with the same tree walker
`_html.py` uses. The only TEI-specific work is reading `<teiHeader>` for
metadata and treating each top-level element of `<body>` (typically a `<div>`
per chapter/book) as its own top-level `Unit`, so a large edition (a
multi-book bible, a multi-volume critical edition) can be converted one
division at a time.
"""

from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag

from ._html import attr_str, element_to_unit
from .schema import DocumentMetadata, Parser, SourceFormat, Unit, read_source_bytes


def _load(source: str) -> BeautifulSoup:
    return BeautifulSoup(read_source_bytes(source), "xml")


def _text(container: Tag, name: str) -> str | None:
    tag = container.find(name)
    return tag.get_text(strip=True) if tag else None


def _promote_head(unit: Unit) -> Unit:
    """Lift a TEI division's `<head>` child up into `Unit.label`."""
    if unit.children and unit.children[0].type == "head":
        head = unit.children.pop(0)
        unit.label = " ".join(_flatten_tokens(head))
    return unit


def _flatten_tokens(unit: Unit) -> list[str]:
    if unit.tokens:
        return [token.text for token in unit.tokens]
    words: list[str] = []
    for child in unit.children:
        words.extend(_flatten_tokens(child))
    return words


class TeiParser(Parser):
    format = SourceFormat.TEI

    def parse_metadata(self, source: str) -> DocumentMetadata:
        soup = _load(source)
        header = soup.find("teiHeader")
        if header is None:
            return DocumentMetadata(source_format=SourceFormat.TEI)

        language_tag = header.find("language")
        return DocumentMetadata(
            source_format=SourceFormat.TEI,
            title=_text(header, "title"),
            creators=[tag.get_text(strip=True) for tag in header.find_all("author")],
            language=attr_str(language_tag, "ident") if language_tag else None,
            publisher=_text(header, "publisher"),
            date=_text(header, "date"),
            identifier=_text(header, "idno"),
            rights=_text(header, "availability"),
        )

    def iter_units(self, source: str) -> Iterator[Unit]:
        soup = _load(source)
        body = soup.find("body") or soup.find("text") or soup
        for child in body.contents:
            if isinstance(child, Tag):
                yield _promote_head(element_to_unit(child))
