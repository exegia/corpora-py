"""
PDF to Text-Fabric Converter

Text-based PDFs route through `pdf_inspector` (issue #175): the PDF is
reduced to markdown whose heading hierarchy becomes nested `section` units
(`admin.parsers._markdown`), *replacing* the legacy flat per-page nodes —
heading structure is what readers navigate by; page numbers don't survive
the reflow. A `mixed` PDF converts its native-text pages and reports the
OCR-needing pages as warnings; a `scanned`/`image_based` PDF is rejected
(no text layer to convert — the upload gate in `admin.services` already
422s these, this is defense in depth). If `pdf_inspector` cannot handle the
file at all, the legacy pypdf per-page route is the fallback.

Node Types (markdown route):
- book: Root node for the entire PDF
- section: A heading-delimited division (heading depth in `level`); level-1
  sections are promoted to `chapter` when the resolved category is `book`
  (issue #176)
- paragraph: A blank-line-separated block
- word: Individual words (slots)

Node Types (legacy per-page fallback):
- book / page / word, with `page_number` on each page.

Features:
- title, creators, date, subjects, ...: document metadata
- label: section heading text; level: heading depth
- text, after: word text and its trailing whitespace
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..parsers import PdfParser
from ..parsers._markdown import markdown_to_units
from ..parsers.schema import (
    CorpusCategory,
    Document,
    read_source_bytes,
)
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents

logger = logging.getLogger(__name__)

# pdf_inspector classifications with enough of a text layer to convert.
_TEXT_BEARING = frozenset({"text_based", "mixed"})


def _otype_for_markdown(unit):
    return unit.type if unit.type in ("section", "paragraph") else "element"


def _markdown_document(source: str, data: bytes) -> tuple[Document, list[str]]:
    """Parse `source` via pdf_inspector markdown; raises on unusable PDFs."""
    import pdf_inspector

    result = pdf_inspector.process_pdf_bytes(data)
    if result.pdf_type not in _TEXT_BEARING:
        raise ValueError(
            f"PDF has no extractable text layer (classified {result.pdf_type!r}); "
            "OCR is required before conversion"
        )
    units = markdown_to_units(result.markdown or "")
    if not units:
        raise ValueError("PDF produced no extractable text")

    # pypdf still reads the metadata dictionary (title, author, dates) --
    # pdf_inspector's markdown carries structure, not document info.
    metadata = PdfParser().parse_metadata(source)
    if not metadata.title and result.title:
        metadata.title = result.title

    warnings: list[str] = []
    skipped = sorted(page + 1 for page in result.pages_needing_ocr or [])
    if skipped:
        pages = ", ".join(str(page) for page in skipped)
        warnings.append(
            f"{len(skipped)} page(s) need OCR and were skipped: {pages}"
        )
    return Document(metadata=metadata, units=units), warnings


def convert_pdf_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Convert a PDF at `source` (path or URL) into a Text-Fabric dataset."""
    data = read_source_bytes(source)
    try:
        document, warnings = _markdown_document(source, data)
    except ValueError:
        # Unusable text layer -- a real rejection, not a fallback case.
        raise
    except Exception:
        logger.warning(
            "pdf_inspector failed for %s; falling back to per-page extraction",
            source,
            exc_info=True,
        )
        return _convert_per_page(source, output_dir, category=category)

    parser = PdfParser()
    effective, spec, otype_for, category_warnings = categorize(
        [document],
        category,
        root_type="book",
        base_otype_for=_otype_for_markdown,
        max_category=CorpusCategory.BOOK,
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
    result.warnings.extend(warnings + category_warnings)
    return result


def _convert_per_page(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None,
) -> ConvertedDataset:
    """Legacy pypdf route: one flat `page` node per PDF page."""
    parser = PdfParser()
    document = parser.parse(source)
    effective, spec, otype_for, warnings = categorize(
        [document],
        category,
        root_type="book",
        base_otype_for=lambda unit: "page",
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
