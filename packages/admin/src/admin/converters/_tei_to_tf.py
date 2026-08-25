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
- book / chapter / verse: divisions promoted from `div` when the resolved
  corpus category (`book` / `religious`, issue #176) declares them as
  Text-Fabric section levels — a `<div type="chapter">` in a `religious`
  corpus lands as a `chapter` node, not a generic `div`
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
from ..parsers.schema import CorpusCategory, Unit
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents


def _otype_for(unit: Unit) -> str:
    if unit.type == "div":
        return "div"
    if unit.type == "p":
        return "paragraph"
    return "element"


def convert_tei_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Convert a TEI document at `source` (path or URL) into a Text-Fabric dataset."""
    parser = TeiParser()
    document = parser.parse(source)
    effective, spec, otype_for, warnings = categorize(
        [document],
        category,
        root_type="text",
        base_otype_for=_otype_for,
    )
    result = convert_documents(
        [document],
        output_dir,
        root_type="text",
        otype_for=otype_for,
        format_value=parser.format.value,
        source_label=source,
        section_spec=spec,
        category=effective,
    )
    result.warnings.extend(warnings)
    return result
