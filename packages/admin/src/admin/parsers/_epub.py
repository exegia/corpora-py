"""
EPUB parser — converts an EPUB ebook into the shared Document/Unit schema.

Each spine document (chapter/page) becomes its own top-level `Unit`, which is
the natural point at which a large EPUB (a novel, a multi-volume work) can be
split for asynchronous, per-chapter conversion. Chapter content is HTML, so
it's walked with the same tree walker `_html.py` uses.
"""

from collections.abc import Iterator

from .epub_structure import read_epub_structure
from .schema import DocumentMetadata, Parser, SourceFormat, Unit


class EpubParser(Parser):
    format = SourceFormat.EPUB

    def parse_metadata(self, source: str) -> DocumentMetadata:
        return read_epub_structure(source).metadata

    def iter_units(self, source: str) -> Iterator[Unit]:
        for i, section in enumerate(read_epub_structure(source).sections):
            yield Unit(
                type=section.role,
                id=f"epub-section-{i + 1}",
                label=section.label,
                attrs={"name": section.source_path, "source-fragment": section.fragment},
                children=[section.unit],
            )
