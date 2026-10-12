"""Pinned forced PDF OCR to Text-Fabric, preserving explicit pages and blocks."""

import shutil
from pathlib import Path

from ..parsers.pdf_ocr import encoded, extract_pdf
from ..parsers.schema import CorpusCategory
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents


def convert_pdf_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Convert all OCR pages without falling back to native text or skipping scans."""
    if source.startswith(("http://", "https://")):
        raise ValueError("Pinned PDF OCR requires a supplied local PDF file")
    extraction = extract_pdf(Path(source))
    document = extraction.document
    warnings = ["PDF OCR source reliability has not been scored; visual source comparison is required"]

    effective, spec, otype_for, category_warnings = categorize(
        [document],
        category,
        root_type="book",
        base_otype_for=lambda unit: unit.type,
        max_category=CorpusCategory.BOOK,
    )
    result = convert_documents(
        [document],
        output_dir,
        root_type="book",
        otype_for=otype_for,
        format_value="pdf",
        source_label=source,
        section_spec=spec,
        category=effective,
    )
    evidence = Path(result) / "pdf-ocr"
    evidence.mkdir()
    (evidence / "snapshot.json").write_bytes(encoded(extraction.snapshot))
    (evidence / "provenance.json").write_bytes(encoded(extraction.provenance))
    shutil.copyfile(source, evidence / "source.pdf")
    result.warnings.extend(warnings + category_warnings)
    return result
