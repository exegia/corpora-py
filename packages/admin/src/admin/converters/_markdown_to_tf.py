"""Markdown through the existing Text-Fabric/Context-Fabric corpus pipeline."""

from pathlib import Path

from ..parsers.markdown_source import MarkdownParser
from ..parsers.schema import CorpusCategory
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents


def convert_markdown_to_tf(
    source: str, output_dir: str | Path, *, category: CorpusCategory | None = None
) -> ConvertedDataset:
    parser = MarkdownParser()
    document = parser.parse(source)
    effective, spec, otype_for, warnings = categorize(
        [document],
        category,
        root_type="document",
        base_otype_for=lambda unit: "element",
        max_category=CorpusCategory.DOCUMENT,
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
