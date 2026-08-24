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
from ._walker import convert_document


def convert_xml_to_tf(source: str, output_dir: str | Path) -> Path:
    """Convert an XML document at `source` (path or URL) into a Text-Fabric dataset."""
    return convert_document(
        XmlParser(),
        source,
        output_dir,
        root_type="document",
        otype_for=lambda unit: "element",
    )
