"""
HTML to Text-Fabric Converter

Converts HTML documents into Text-Fabric (TF) datasets using the tf.convert.walker library.
This allows HTML content to be queried using Context-Fabric's powerful graph query API.

Features:
- Preserves HTML structure as a node hierarchy
- Creates slots for text content (words/tokens)
- Stores HTML attributes as node features
- Supports nested HTML elements
- Generates valid Text-Fabric datasets

Node Types:
- document: Root node for each HTML document
- element: HTML tags (div, p, span, etc.)
- word: Individual words (slots)

Features:
- tag: HTML tag name (div, p, span, etc.)
- class: CSS class names
- id: HTML id attribute
- href: Link URLs (for <a> tags)
- src: Source URLs (for <img>, <script> tags)
- text: Raw text content
- * (any HTML attribute preserved as feature)
"""

from pathlib import Path

from ..parsers import HtmlParser
from ._walker import convert_document


def convert_html_to_tf(source: str, output_dir: str | Path) -> Path:
    """Convert an HTML document at `source` (path or URL) into a Text-Fabric dataset."""
    return convert_document(
        HtmlParser(),
        source,
        output_dir,
        root_type="document",
        otype_for=lambda unit: "element",
    )
