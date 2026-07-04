"""Format-specific parsers, all converting into the shared schema in `schema.py`."""

from ._epub import EpubParser
from ._html import HtmlParser
from ._pdf import PdfParser
from ._plain import PlainTextParser
from ._tei import TeiParser
from ._xml import XmlParser
from .schema import Document, DocumentMetadata, Parser, SourceFormat, Token, Unit

PARSERS: dict[SourceFormat, Parser] = {
    SourceFormat.EPUB: EpubParser(),
    SourceFormat.HTML: HtmlParser(),
    SourceFormat.XML: XmlParser(),
    SourceFormat.TEI: TeiParser(),
    SourceFormat.PDF: PdfParser(),
    SourceFormat.PLAIN: PlainTextParser(),
}

__all__ = [
    "Document",
    "DocumentMetadata",
    "EpubParser",
    "HtmlParser",
    "PARSERS",
    "Parser",
    "PdfParser",
    "PlainTextParser",
    "SourceFormat",
    "TeiParser",
    "Token",
    "Unit",
    "XmlParser",
]
