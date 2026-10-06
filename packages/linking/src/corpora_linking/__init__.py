"""Public linking core, independent of Corpora, storage and source parsers."""

from .interfaces import Detector, PublicationAdapter, ReferenceStore, Resolver
from .locators import normalize_text, verify_text_anchor
from .models import (
    CitationLocator,
    ConversionMapping,
    Endpoint,
    EpubLocator,
    Locator,
    PdfLocator,
    PdfRectangle,
    Provenance,
    Reference,
    ResolutionResult,
    StructuralLocator,
    TextLocator,
)

__all__ = [
    "CitationLocator",
    "ConversionMapping",
    "Detector",
    "Endpoint",
    "EpubLocator",
    "Locator",
    "PdfLocator",
    "PdfRectangle",
    "Provenance",
    "PublicationAdapter",
    "Reference",
    "ReferenceStore",
    "ResolutionResult",
    "Resolver",
    "StructuralLocator",
    "TextLocator",
    "normalize_text",
    "verify_text_anchor",
]
