"""
Markdown → `Unit` tree (issue #175).

Not a registered `Parser` (markdown is not a `SourceFormat`): this backs the
PDF conversion route, where `pdf_inspector.process_pdf` reduces a text-based
PDF to markdown whose heading hierarchy *is* the document structure — the
converter turns that into nested `section` units instead of the legacy flat
per-page nodes.

Only the structure this pipeline needs is parsed: ATX headings (``#`` …
``######``) open nested ``section`` units (heading depth = nesting depth,
kept in ``attrs["level"]``; the heading text becomes the section `label`),
and blank-line-separated blocks in between become ``paragraph`` units.
Fenced code blocks are kept as paragraph text (a ``#`` inside a fence is not
a heading). Anything fancier (tables, lists, emphasis) flows through as
plain paragraph text — the corpus wants the words, not the markup.
"""

from __future__ import annotations

import re

from .schema import Unit, tokenize

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^(```|~~~)")


def markdown_to_units(text: str) -> list[Unit]:
    """Parse markdown into nested ``section``/``paragraph`` `Unit`s.

    Heading levels may skip (an ``###`` right after a ``#``): a heading
    nests under the closest open section with a smaller level, so the tree
    always mirrors the visual outline.
    """
    top: list[Unit] = []
    # Stack of open sections, shallowest first; content lands in the
    # deepest one (or `top` when no heading has been seen yet).
    stack: list[Unit] = []
    paragraph: list[str] = []
    in_fence = False

    def container() -> list[Unit]:
        return stack[-1].children if stack else top

    def flush_paragraph() -> None:
        nonlocal paragraph
        block = "\n".join(paragraph).strip()
        paragraph = []
        if block:
            container().append(Unit(type="paragraph", tokens=tokenize(block)))

    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            paragraph.append(line)
            continue
        if in_fence:
            paragraph.append(line)
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            while stack and int(stack[-1].attrs["level"]) >= level:
                stack.pop()
            section = Unit(
                type="section",
                label=heading.group(2) or None,
                attrs={"level": str(level)},
            )
            container().append(section)
            stack.append(section)
            continue
        if not line.strip():
            flush_paragraph()
            continue
        paragraph.append(line)

    flush_paragraph()
    return top
