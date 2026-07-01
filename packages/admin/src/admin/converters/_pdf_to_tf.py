"""
PDF to Text-Fabric Converter

Converts PDF files into Text-Fabric datasets using the pdf parser for
extraction and the tf.convert.walker library for TF generation.

Features:
- Extracts PDF metadata (title, author, producer, etc.)
- One node per page, so a large PDF converts one page at a time
- Tracks conversion progress

Node Types:
- book: Root node for the entire PDF
- page: Individual pages
- word: Individual words (slots)

Features:
- title, creators, date, subjects, ...: document metadata
- page_number: 1-based page number
- text, after: word text and its trailing whitespace
"""

from pathlib import Path

from ..parsers import PdfParser
from ._walker import convert_document


def convert_pdf_to_tf(source: str, output_dir: str | Path) -> Path:
    """Convert a PDF at `source` (path or URL) into a Text-Fabric dataset."""
    return convert_document(
        PdfParser(),
        source,
        output_dir,
        root_type="book",
        otype_for=lambda unit: "page",
    )
