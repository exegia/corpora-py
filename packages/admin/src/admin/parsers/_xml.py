"""
Generic XML parser — converts an arbitrary XML document into the shared
Document/Unit schema. Tag names become `Unit.type` and attributes become
`Unit.attrs`; no domain-specific structure (like TEI's) is assumed.
"""

from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag

from ._html import element_to_unit, unit_attrs
from .schema import DocumentMetadata, Parser, SourceFormat, Unit, read_source_bytes


def _load(source: str) -> BeautifulSoup:
    return BeautifulSoup(read_source_bytes(source), "xml")


def _root(soup: BeautifulSoup) -> Tag | None:
    return soup.find(True)


class XmlParser(Parser):
    format = SourceFormat.XML

    def parse_metadata(self, source: str) -> DocumentMetadata:
        soup = _load(source)
        root = _root(soup)
        title_tag = soup.find(["title", "Title"])
        return DocumentMetadata(
            source_format=SourceFormat.XML,
            title=title_tag.get_text(strip=True) if title_tag else (root.name if root else None),
            extra=unit_attrs(root) if root else {},
        )

    def iter_units(self, source: str) -> Iterator[Unit]:
        soup = _load(source)
        root = _root(soup)
        if root is None:
            return

        element_children = [child for child in root.contents if isinstance(child, Tag)]
        if not element_children:
            # A leaf-only document: the root itself is the one unit.
            yield element_to_unit(root)
            return

        for child in element_children:
            yield element_to_unit(child)
