"""
Plain Text to Text-Fabric Converter

Converts raw text files into Text-Fabric datasets using the plain-text
parser for extraction and the tf.convert.walker library for TF generation.

Features:
- One node per paragraph (blank-line-separated), so a large plain-text
  corpus converts one paragraph at a time
- Minimal metadata (a title derived from the file name)

Node Types:
- book: Root node for the entire text file
- paragraph: A blank-line-separated block of text
- word: Individual words (slots)

Features:
- title: derived from the source file name
- text, after: word text and its trailing whitespace
"""

from pathlib import Path

from ..parsers import PlainTextParser
from ._walker import convert_document


def convert_text_to_tf(source: str, output_dir: str | Path) -> Path:
    """Convert a plain-text file at `source` (path or URL) into a Text-Fabric dataset."""
    return convert_document(
        PlainTextParser(),
        source,
        output_dir,
        root_type="book",
        otype_for=lambda unit: "paragraph",
    )
