"""Corpus-detail logic: read/update a `.corpus` archive's metadata, index, and content.

The desktop app's detail view needs three things from a stored `.corpus`
archive that plain Hub storage (`storage.py`) doesn't give it:

- its ``manifest.yml`` (read + patch a subset of metadata fields),
- an *index* of its section structure (books/chapters/pages) plus node-type
  counts, so a reader can navigate it, and
- its *content*, paginated by section reference.

All three need the archive's bytes locally: this module downloads the archive
from the Hub (reusing `CorpusStorage`), extracts it, and -- for index/content
-- loads the Text-Fabric payload under ``corpora/`` with `cfabric.Fabric`. The
extracted directory and the loaded api are cached in-process, keyed by the
archive filename; a manifest PATCH re-uploads the archive and invalidates that
cache so the next read re-fetches the updated bytes.

Everything here is blocking (Hub network I/O, zip extraction, cfabric loading),
so the async surfaces (`corpus_detail_api.py`, `corpus_detail_mcp.py`) must call
through ``asyncio.to_thread`` -- the same rule the rest of `admin.services`
follows.

`corpus_storage`, `_HUB_CACHE_ROOT`, and the in-process cache are all
module-level names so tests can monkeypatch a fake `corpus_storage` in one place
and have it cover the REST router and the MCP tools alike (both route through
the functions here).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .storage import (
    CorpusNotFoundError,
    StorageError,
    corpus_storage,
)

logger = logging.getLogger(__name__)

_CORPUS_SUFFIX = ".corpus"

# Where archives fetched from the Hub are materialized + extracted. Like
# `storage_api._HUB_CACHE_ROOT` and `api._RESULTS_ROOT`, nothing reaps this yet
# -- same TTL-cleanup gap tracked in `packages/admin/CLAUDE.md`.
_HUB_CACHE_ROOT = Path(tempfile.gettempdir()) / "corpora-admin-corpus-detail-cache"

# How many child sections (chapters/pages) to list per top-level index item
# before truncating -- a big book can have thousands of chapters and the detail
# view only needs a navigable slice.
_MAX_CHILDREN = 500

# Manifest keys a PATCH is allowed to touch (all optional strings). Kept here so
# the REST/MCP surfaces and this module agree on the editable subset.
_EDITABLE_MANIFEST_KEYS = frozenset(
    {
        "name",
        "description",
        "version",
        "language",
        "languageCode",
        "type",
        "category",
        "written_date",
    }
)


@dataclass
class _Cached:
    """One archive's local footprint: its extracted dir and (lazily) its api."""

    extract_dir: Path
    api_loaded: bool = False
    api: Any = None


# filename -> _Cached. Guarded by `_lock`; never nest lock acquisitions.
_cache: dict[str, _Cached] = {}
_lock = threading.Lock()


def _safe_name(filename: str) -> str:
    """Normalize to a flat ``<name>.corpus`` filename, rejecting path escapes.

    Mirrors `storage._safe_archive_name` -- the storage repo and this cache are
    flat namespaces and a filename must never escape either.
    """
    name = Path(filename).name
    if name in ("", ".", "..") or name == _CORPUS_SUFFIX:
        raise CorpusNotFoundError(f"Invalid corpus filename: {filename!r}")
    if not name.endswith(_CORPUS_SUFFIX):
        name += _CORPUS_SUFFIX
    return name


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract `zf` into `dest`, rejecting any member that escapes `dest`."""
    dest = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not target.is_relative_to(dest):
            raise StorageError(f"Unsafe path in corpus archive: {member.filename!r}")
    zf.extractall(dest)


def _ensure_extracted(filename: str) -> _Cached:
    """Return the cache entry for `filename`, downloading + extracting if absent."""
    name = _safe_name(filename)
    with _lock:
        cached = _cache.get(name)
        if cached is not None:
            return cached

        work = _HUB_CACHE_ROOT / name
        download_dir = work / "download"
        extract_dir = work / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
        download_dir.mkdir(parents=True, exist_ok=True)

        # Raises CorpusNotFoundError / StorageNotConfiguredError / StorageError,
        # which the callers map to 404 / 503 / 502.
        archive = corpus_storage.download(name, dest_dir=download_dir)

        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf:
            _safe_extract(zf, extract_dir)

        cached = _Cached(extract_dir=extract_dir)
        _cache[name] = cached
        return cached


def _load_api(filename: str) -> Any:
    """Load (and cache) the cfabric api for `filename`; None if it won't load."""
    cached = _ensure_extracted(filename)
    with _lock:
        if cached.api_loaded:
            return cached.api

    from cfabric import Fabric  # local import: keep module import cfabric-free

    corpora_dir = cached.extract_dir / "corpora"
    result = Fabric(locations=str(corpora_dir), silent="deep").loadAll(silent="deep")
    # loadAll() returns `Api | bool` (False on failure); narrow before use.
    api = None if isinstance(result, bool) else result

    with _lock:
        cached.api_loaded = True
        cached.api = api
    return api


def invalidate(filename: str) -> None:
    """Drop the cached extraction + api for `filename` and delete its files."""
    name = _safe_name(filename)
    with _lock:
        cached = _cache.pop(name, None)
    work = _HUB_CACHE_ROOT / name
    shutil.rmtree(work, ignore_errors=True)
    if cached is not None:
        logger.debug("Invalidated corpus-detail cache for %s", name)


# ── Section-reference helpers (adapted from corpora_mcp.server) ────────────────


def _section_ref(node: int, api: Any) -> str:
    """Human-readable section reference for `node` (its enclosing section)."""
    try:
        parts = api.T.sectionFromNode(node)
        ref = " ".join(str(p) for p in parts if p is not None)
        return ref or str(node)
    except Exception:
        return str(node)


def _section_label(node: int, api: Any) -> str:
    """The local label for `node` -- the last part of its section reference."""
    try:
        parts = api.T.sectionFromNode(node)
        cleaned = [str(p) for p in parts if p is not None]
        if cleaned:
            return cleaned[-1]
    except Exception:
        pass
    return str(node)


def _parse_section_ref(ref: str, api: Any) -> tuple[Any, ...] | None:
    """Parse a human-readable reference into a section tuple.

    Adapted from `corpora_mcp.server._parse_section_ref`, with one crucial
    difference: this repo's converters emit *single-section-level* corpora (one
    root node with a ``title``), so the reference our own index produces is just
    that title -- which may end in a number (``"Psalm 23"``). The upstream
    parser would split that trailing number off and fail to resolve it; here a
    single-level corpus always maps the whole string to a one-element tuple.
    """
    ref = ref.strip()
    try:
        n = len(api.T.sectionTypes)
    except Exception:
        n = 3  # assume book/chapter/verse if unknown

    if n <= 1:
        return (ref,)

    if ":" in ref:
        head, verse = ref.rsplit(":", 1)
        tokens = head.split()
        if not tokens:
            return None
        try:
            if len(tokens) > 1:
                book = " ".join(tokens[:-1])
                return (book, int(tokens[-1]), int(verse))
            return (tokens[0], int(verse))
        except ValueError:
            return None

    tokens = ref.split()
    if len(tokens) >= 2:
        try:
            last = int(tokens[-1])
            return (" ".join(tokens[:-1]), last)
        except ValueError:
            pass
    return (ref,)


def _resolve_section_node(api: Any, ref: str, levels: list[str]) -> int | None:
    """Resolve a human-readable section reference to its node, or None.

    Tries `T.nodeFromSection` first (works for language-aware multi-level
    corpora like BHSA). Falls back to matching the reference string against the
    section ref each node reports -- required for the single-level corpora this
    repo's converters produce, where the section feature (``title``) carries no
    language and `nodeFromSection` can't look it up. Matching against the
    emitted ref guarantees the index -> content round-trip.
    """
    parts = _parse_section_ref(ref, api)
    if parts is not None:
        try:
            node = api.T.nodeFromSection(parts)
        except Exception:
            node = None
        if node is not None:
            return int(node)

    target = ref.strip()
    for otype in levels:
        for node in api.F.otype.s(otype):
            if _section_ref(node, api) == target:
                return int(node)
    return None


def _finest_otype(api: Any) -> str:
    """The finest non-slot node type (paragraph/element/line above the slot)."""
    all_types = list(api.F.otype.all or ())
    slot = api.F.otype.slotType
    non_slot = [t for t in all_types if t != slot]
    # `F.otype.all` runs big -> small, so the last non-slot type is the finest.
    return non_slot[-1] if non_slot else slot


# ── Manifest ──────────────────────────────────────────────────────────────────


def get_manifest(filename: str) -> dict[str, Any]:
    """Return the archive's ``manifest.yml`` as a dict (unknown keys preserved)."""
    cached = _ensure_extracted(filename)
    path = cached.extract_dir / "manifest.yml"
    if not path.is_file():
        raise CorpusNotFoundError(f"No manifest.yml in {_safe_name(filename)}")
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, dict) else {}


def update_manifest(filename: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Patch a subset of manifest fields, re-upload the archive, return the full manifest.

    Loads the existing manifest, overwrites only the provided (editable) keys,
    dumps it back, re-zips the extracted archive, uploads it to the Hub, and
    invalidates the local cache so the next read re-fetches the updated bytes.
    """
    editable = {k: v for k, v in updates.items() if k in _EDITABLE_MANIFEST_KEYS}
    if not editable:
        raise StorageError("No editable manifest fields provided")

    cached = _ensure_extracted(filename)
    manifest_path = cached.extract_dir / "manifest.yml"
    if not manifest_path.is_file():
        raise CorpusNotFoundError(f"No manifest.yml in {_safe_name(filename)}")

    manifest = yaml.safe_load(manifest_path.read_text())
    if not isinstance(manifest, dict):
        manifest = {}
    manifest.update(editable)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    name = _safe_name(filename)
    with tempfile.TemporaryDirectory(prefix="corpus-detail-") as tmp:
        base = Path(tmp) / Path(name).stem
        archive = shutil.make_archive(str(base), "zip", root_dir=cached.extract_dir)
        out = Path(tmp) / name
        Path(archive).rename(out)
        corpus_storage.upload(out, name)

    invalidate(name)
    logger.info("Updated manifest for %s (%s)", name, sorted(editable))
    return manifest


# ── Index ─────────────────────────────────────────────────────────────────────


def _build_sections(api: Any) -> dict[str, Any] | None:
    """Top-level section nodes with their immediate child sections, or None."""
    try:
        levels = list(api.T.sectionTypes)
    except Exception:
        levels = []
    if not levels:
        return None

    top_type = levels[0]
    child_type = levels[1] if len(levels) > 1 else None

    items: list[dict[str, Any]] = []
    for node in api.F.otype.s(top_type):
        children: list[dict[str, str]] = []
        if child_type is not None:
            for child in api.L.d(node, otype=child_type)[:_MAX_CHILDREN]:
                child_ref = _section_ref(child, api)
                children.append(
                    {"title": _section_label(child, api) or child_ref, "ref": child_ref}
                )
        item_ref = _section_ref(node, api)
        items.append(
            {
                "title": _section_label(node, api) or item_ref,
                "ref": item_ref,
                "children": children,
            }
        )

    return {"levels": levels, "items": items}


def get_index(filename: str) -> dict[str, Any]:
    """Return the archive's toc, section structure, and node-type counts."""
    cached = _ensure_extracted(filename)
    toc_path = cached.extract_dir / "toc.yml"
    toc = yaml.safe_load(toc_path.read_text()) if toc_path.is_file() else None

    api = _load_api(filename)
    if api is None:
        return {"toc": toc, "sections": None, "node_types": []}

    node_types = [
        {"type": t, "count": len(api.F.otype.s(t))} for t in (api.F.otype.all or ())
    ]
    sections = _build_sections(api)
    return {"toc": toc, "sections": sections, "node_types": node_types}


# ── Content ───────────────────────────────────────────────────────────────────


def _passage_nodes(api: Any, section_node: int | None, levels: list[str]) -> list[int]:
    """Choose the passage nodes to paginate (lowest section level or finest slot-bearing)."""
    lowest = levels[-1] if levels else None

    if section_node is None:
        # Whole corpus. A multi-level corpus paginates its lowest section level;
        # a single-level one has only the root at that level (one giant node),
        # so fall back to the finest slot-bearing type (paragraphs/elements).
        if levels and len(levels) > 1 and lowest is not None:
            return list(api.F.otype.s(lowest))
        return list(api.F.otype.s(_finest_otype(api)))

    node_type = api.F.otype.v(section_node)
    idx = levels.index(node_type) if node_type in levels else 0

    # If a finer section level exists below this node, list those sections.
    if levels and idx < len(levels) - 1 and lowest is not None:
        nodes = list(api.L.d(section_node, otype=lowest))
        if nodes:
            return nodes

    # Otherwise (node is at the lowest section level, e.g. a single-level root)
    # descend to the finest slot-bearing type that yields text.
    finest = _finest_otype(api)
    nodes = list(api.L.d(section_node, otype=finest))
    return nodes if nodes else [section_node]


def get_content(
    filename: str,
    ref: str | None = None,
    fmt: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return paginated passages under `ref` (or the whole corpus if omitted).

    A `ref` that doesn't resolve to a section raises `CorpusNotFoundError`
    (mapped to 404 by the callers).
    """
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    api = _load_api(filename)
    if api is None:
        return {
            "ref": ref,
            "format": fmt or "",
            "passages": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "next_offset": None,
        }

    try:
        fmt_used = fmt or api.T.defaultFormat
    except Exception:
        fmt_used = fmt or ""

    try:
        levels = list(api.T.sectionTypes)
    except Exception:
        levels = []

    section_node: int | None = None
    if ref:
        node = _resolve_section_node(api, ref, levels)
        if node is None:
            raise CorpusNotFoundError(
                f"Section reference {ref!r} not found in {_safe_name(filename)}"
            )
        section_node = node

    passage_nodes = _passage_nodes(api, section_node, levels)
    total = len(passage_nodes)
    page = passage_nodes[offset : offset + limit]

    passages: list[dict[str, str]] = []
    for node in page:
        try:
            text = api.T.text(node, fmt=fmt_used) if fmt_used else api.T.text(node)
        except Exception as exc:  # noqa: BLE001 - degrade to empty, don't fail the page
            logger.debug("text() failed for node %s: %s", node, exc)
            text = ""
        passages.append({"ref": _section_ref(node, api), "text": text})

    next_offset = offset + limit if offset + limit < total else None
    return {
        "ref": ref,
        "format": fmt_used,
        "passages": passages,
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
    }
