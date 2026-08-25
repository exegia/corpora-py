"""
Generic XML to Text-Fabric Converter

Converts XML documents into Text-Fabric (TF) datasets using the shared
walker. Tag names become `Unit.type` and attributes become node features;
no domain-specific structure (like TEI's ``<div>``/``<p>`` convention) is
assumed — every element maps to a generic ``element`` otype, matching the
HTML converter's approach (the XML parser already reuses ``element_to_unit``
from ``_html.py``).

Node Types:
- document: Root node for each XML document
- element: XML tags (any tag name)
- word: Individual words (slots)

Features:
- tag: XML tag name
- text: Raw text content
- * (any XML attribute preserved as feature)
"""

from pathlib import Path

from ..parsers import XmlParser
from ..parsers.schema import CorpusCategory
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents


def convert_xml_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Convert an XML document at `source` (path or URL) into a Text-Fabric dataset.

    The generic ``element`` mapping still holds, with one structural
    exception (issue #176): tag names / ``type`` attributes that carry a
    section role (``<book>``, ``<chapter type="...">``, ``<verse>``) are
    promoted to those section otypes when the resolved category declares
    them — generic XML is how bibles frequently arrive.
    """
    parser = XmlParser()
    document = parser.parse(source)
    effective, spec, otype_for, warnings = categorize(
        [document],
        category,
        root_type="document",
        base_otype_for=lambda unit: "element",
    )
    result = convert_documents(
        [document],
        output_dir,
        root_type="document",
        otype_for=otype_for,
        format_value=parser.format.value,
        source_label=source,
        section_spec=spec,
        category=effective,
    )
    result.warnings.extend(warnings)
    return result
