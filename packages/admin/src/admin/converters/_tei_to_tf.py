"""
TEI to Text-Fabric Converter

Converts TEI (Text Encoding Initiative) XML documents into Text-Fabric
datasets using the tei parser for extraction and the tf.convert.walker
library for TF generation.

Features:
- Extracts teiHeader metadata (title, author, publisher, date, ...)
- Preserves the TEI division hierarchy (<div> nesting)
- Lifts each division's <head> into a `label` feature
- One node per top-level division, so a large edition (a multi-book bible,
  a multi-volume critical edition) converts one division at a time

Node Types:
- text: Root node for the entire TEI document
- div: A TEI division (chapter, book, ...); its `type` attribute survives
  as an ordinary feature (e.g. `type="chapter"`)
- paragraph: <p> elements
- element: Any other TEI element (l, seg, note, ...)
- word: Individual words (slots)

Features:
- title, creators, language, publisher, date, identifier, rights: document metadata
- label: division heading, lifted from its <head> child
- type: TEI `@type` attribute (e.g. div type="chapter")
- text, after: word text and its trailing whitespace
"""

from pathlib import Path

from ..parsers import TeiParser
from ..parsers.schema import Unit
from ._walker import convert_document


def _otype_for(unit: Unit) -> str:
    if unit.type == "div":
        return "div"
    if unit.type == "p":
        return "paragraph"
    return "element"


def convert_tei_to_tf(source: str, output_dir: str | Path) -> Path:
    """Convert a TEI document at `source` (path or URL) into a Text-Fabric dataset."""
    return convert_document(
        TeiParser(),
        source,
        output_dir,
        root_type="text",
        otype_for=_otype_for,
    )
