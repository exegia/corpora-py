"""Presentation helpers for reference identifiers (`common.utils.tfref`).

`tfref` owns the grammar and resolution rules; this module owns everything a
UI needs *around* a reference -- a human label, a compact pill token, a share
URL, and the corpus metadata block that travels with a resolved reference.
Shared by the `/refs` REST router and both MCP surfaces so all three agree on
the payload shape.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .config import settings
from .tfref import Adapter, Ref

# Two-letter tags for the pill / compact token. Mirrors the level prefixes in
# docs/architecture/inter-corpus-refs.md so the UI vocabulary stays the same.
_ABBREV = {
    "word": "wo",
    "clause": "cl",
    "phrase": "ph",
    "sentence": "st",
    "paragraph": "pa",
    "para": "pa",
    "verse": "vs",
    "line": "ln",
    "chapter": "ch",
    "book": "bk",
}


def abbrev(otype: str) -> str:
    return _ABBREV.get(otype, otype[:2].lower())


def selector_label(ref: Ref) -> str:
    """'clause 1', 'words 3-5', or '' for a bare section reference."""
    if not ref.target_type:
        return ""
    if ref.is_range:
        return f"{ref.target_type}s {ref.start}-{ref.end}"
    return f"{ref.target_type} {ref.start}"


def section_label(sections: tuple[Any, ...]) -> str:
    """'Deut 4:2' style: first level, then space, then ':'-joined numbers."""
    parts = [str(s) for s in sections]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {':'.join(parts[1:])}"


def label_for(ref: Ref) -> str:
    """Human label for a pill or a tooltip: 'Deut 4:2 · clause 1'."""
    head = section_label(ref.sections)
    sel = selector_label(ref)
    return f"{head} · {sel}" if sel else head


def compact_for(ref: Ref) -> str:
    """Compact token for inline pills: 'Deut 4:2 cl1', 'Deut 4:2 wo3-5'."""
    head = section_label(ref.sections)
    if not ref.target_type:
        return head
    sel = f"{abbrev(ref.target_type)}{ref.start}"
    if ref.is_range:
        sel += f"-{ref.end}"
    return f"{head} {sel}"


def share_url(ref_str: str, template: str | None = None) -> str:
    tpl = template or settings.reference_url_template
    return tpl.replace("{ref}", quote(ref_str, safe=""))


def sections_dict(adapter: Adapter, sections: tuple[Any, ...]) -> dict[str, Any]:
    """Zip the section values with the corpus's level names: {'book': 'Deut', ...}.

    Values are cast to the section features' own types (chapter 4, not "4").
    """
    try:
        typed: tuple[Any, ...] = adapter.typed_sections(tuple(sections))
    except Exception:  # noqa: BLE001 - keep the raw strings rather than fail a display
        typed = tuple(sections)
    return {level: value for level, value in zip(adapter.section_types, typed, strict=False)}


def shortcode_payload(
    ref: Ref, ref_str: str, *, url_template: str | None = None, token: str | None = None
) -> dict[str, Any]:
    """Everything a UI needs to render/copy/share one reference.

    `token` is the compact positional serialization (`common.utils.refcompact`)
    when the caller resolved the reference against its corpus; None for a
    foreign reference that was only formatted.
    """
    label = label_for(ref)
    url = share_url(ref_str, url_template)
    urn = ref.urn() if ref.corpus else None
    return {
        "ref": ref_str,
        "urn": urn,
        "token": token,
        "label": label,
        "compact": compact_for(ref),
        "url": url,
        "pill": {"text": compact_for(ref), "title": label, "href": url},
        "markdown": f"[{label}]({url})",
        "html": f'<a class="ref-pill" href="{url}" title="{ref_str}">{label}</a>',
    }


def corpus_metadata(
    *,
    corpus_id: str,
    manifest: dict[str, Any] | None,
    toc: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Normalise `manifest.yml` (+ `toc.yml`) into the block a reference carries.

    The archive's `manifest.yml` is an `ICorpusManifest` (uid, name, description,
    version, language, written_date, ...) and `toc.yml` carries `corpusId`,
    `authorId`, `publisherId`. `corpus_id` is the id used in the reference
    string (the library filename stem for stored archives, the loaded name for
    runtime corpora) -- it is what a client should put back into a reference.
    """
    m = manifest or {}
    t = toc or {}
    written = str(m.get("written_date") or "")
    year = written[:4] if written[:4].isdigit() else None
    authors = t.get("authorId")
    if isinstance(authors, str):
        authors = [authors] if authors else []
    return {
        "corpusId": corpus_id,
        "uid": m.get("uid") or t.get("corpusId"),
        "title": m.get("name"),
        "description": m.get("description"),
        "version": version or m.get("version"),
        "language": m.get("language"),
        "languageCode": m.get("languageCode"),
        "type": m.get("type"),
        "category": m.get("category"),
        "year": year,
        "writtenDate": written or None,
        "authors": authors or [],
        "publisher": t.get("publisherId") or None,
        "datasetId": m.get("datasetId") or None,
        "projectId": m.get("projectId") or None,
    }
