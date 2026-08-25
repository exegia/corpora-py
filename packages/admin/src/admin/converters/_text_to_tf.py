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
from ..parsers.schema import CorpusCategory
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents


def convert_text_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Convert a plain-text file at `source` (path or URL) into a Text-Fabric dataset.

    Blank-line paragraphs carry no chapter/verse structure, so the category
    is always ``document`` — a higher override downgrades with a warning.
    """
    parser = PlainTextParser()
    document = parser.parse(source)
    effective, spec, otype_for, warnings = categorize(
        [document],
        category,
        root_type="book",
        base_otype_for=lambda unit: "paragraph",
        max_category=CorpusCategory.DOCUMENT,
    )
    result = convert_documents(
        [document],
        output_dir,
        root_type="book",
        otype_for=otype_for,
        format_value=parser.format.value,
        source_label=source,
        section_spec=spec,
        category=effective,
    )
    result.warnings.extend(warnings)
    return result
