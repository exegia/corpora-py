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

import json
import logging
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
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
# view only needs a navigable slice. `GET …/sections` is the paginated follow-up.
_MAX_CHILDREN = 500
_MAX_SECTION_PAGE = 200

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


def _slot_span(api: Any, node: int) -> int | None:
    """How many slots `node` covers, or None if it has no oslots."""
    otype = api.F.otype.v(node)
    if otype is None:
        return None
    if otype == api.F.otype.slotType:
        return 1
    try:
        slots = api.E.oslots.s(node)
    except Exception:  # noqa: BLE001 - some nodes have no slot embedding
        return None
    if not slots:
        return None
    return int(slots[-1]) - int(slots[0]) + 1


def _node_type_stats(api: Any) -> list[dict[str, Any]]:
    """Per-otype counts with mean slot span and a slot-type flag."""
    slot_type = api.F.otype.slotType
    rows: list[dict[str, Any]] = []
    for otype in api.F.otype.all or ():
        nodes = list(api.F.otype.s(otype))
        if otype == slot_type:
            avg = 1.0
        else:
            spans = [span for n in nodes if (span := _slot_span(api, n)) is not None]
            avg = (sum(spans) / len(spans)) if spans else 0.0
        rows.append(
            {
                "type": otype,
                "count": len(nodes),
                "avg_slots": round(avg, 1),
                "is_slot": otype == slot_type,
            }
        )
    return rows


def _section_entry(
    api: Any,
    node: int,
    *,
    grandchild_type: str | None = None,
) -> dict[str, Any]:
    """One section row: identity, slot span, and how many section-children it has."""
    ref = _section_ref(node, api)
    otype = api.F.otype.v(node)
    if grandchild_type:
        child_count = len(list(api.L.d(node, otype=grandchild_type)))
    else:
        child_count = 0
    return {
        "title": _section_label(node, api) or ref,
        "ref": ref,
        "otype": str(otype or ""),
        "child_count": child_count,
        "nodes": child_count,
        "words": _slot_span(api, node),
    }


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

    name = _republish(filename, cached)
    logger.info("Updated manifest for %s (%s)", name, sorted(editable))
    return manifest


def _republish(filename: str, cached: _Cached) -> str:
    """Re-zip the extracted archive, upload it, invalidate the cache.

    The shared tail of every archive writer (`update_manifest`,
    `annotate_node`): whoever mutated files under `cached.extract_dir` calls
    this to publish the change. Returns the normalized archive name.
    """
    name = _safe_name(filename)
    with tempfile.TemporaryDirectory(prefix="corpus-detail-") as tmp:
        base = Path(tmp) / Path(name).stem
        archive = shutil.make_archive(str(base), "zip", root_dir=cached.extract_dir)
        out = Path(tmp) / name
        Path(archive).rename(out)
        corpus_storage.upload(out, name)

    invalidate(name)
    return name


# ── Nodes (inspect + annotate) ────────────────────────────────────────────────

# Sidecar file at the archive root (next to manifest.yml) recording node-level
# corrections: {"nodes": {"<node id>": {"otype": ..., "note": ..., ...}}}.
# The converted Text-Fabric payload under corpora/ is never rewritten -- an
# annotation records what the type SHOULD be (plus provenance) so downstream
# consumers and future re-conversions can apply it, without risking the
# binary feature data on an imperfect in-place edit.
_ANNOTATIONS_FILE = "annotations.json"


def _read_annotations(extract_dir: Path) -> dict[str, Any]:
    """Parse the annotations sidecar, tolerating a missing/corrupt file."""
    path = extract_dir / _ANNOTATIONS_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_annotations(filename: str) -> dict[str, Any]:
    """Return the archive's node-annotation sidecar (empty dict if absent)."""
    cached = _ensure_extracted(filename)
    return _read_annotations(cached.extract_dir)


def _require_api(filename: str) -> Any:
    """Load the cfabric api or raise (the node surfaces can't degrade to empty)."""
    api = _load_api(filename)
    if api is None:
        raise CorpusNotFoundError(
            f"Corpus payload in {_safe_name(filename)} could not be loaded"
        )
    return api


def get_node(filename: str, node: int) -> dict[str, Any]:
    """Inspect one node: its type, slot span, text, features, and annotation.

    The graph-model facts an auditor needs in one payload: `otype` as the
    converter emitted it, whether the node is a slot, the slot range it spans,
    every non-None node-feature value, and any correction already recorded in
    the annotations sidecar.
    """
    api = _require_api(filename)
    otype = api.F.otype.v(node)
    if otype is None:
        raise CorpusNotFoundError(f"Node {node} not found in {_safe_name(filename)}")

    slot_type = api.F.otype.slotType
    is_slot = otype == slot_type
    if is_slot:
        first_slot: int | None = int(node)
        last_slot: int | None = int(node)
    else:
        try:
            slots = api.E.oslots.s(node)
            first_slot = int(slots[0]) if len(slots) else None
            last_slot = int(slots[-1]) if len(slots) else None
        except Exception:  # noqa: BLE001 - a node without oslots still has features
            first_slot = last_slot = None

    features: dict[str, Any] = {}
    for name in sorted(api.Fall()):
        if name == "otype":
            continue
        try:
            value = api.Fs(name).v(node)
        except Exception:  # noqa: BLE001 - skip features that fail to look up
            continue
        if value is not None:
            features[name] = value

    try:
        text = api.T.text(node)
    except Exception:  # noqa: BLE001 - some non-slot nodes have no text
        text = ""

    cached = _ensure_extracted(filename)
    annotation = _read_annotations(cached.extract_dir).get("nodes", {}).get(str(node))

    return {
        "node": int(node),
        "otype": otype,
        "is_slot": is_slot,
        "slot_type": slot_type,
        "first_slot": first_slot,
        "last_slot": last_slot,
        "section_ref": _section_ref(node, api),
        "text": text,
        "features": features,
        "annotation": annotation,
        "node_types": [str(t) for t in (api.F.otype.all or ())],
    }


def annotate_node(
    filename: str,
    node: int,
    otype: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record a node-type correction in the annotations sidecar and republish.

    Merges into the node's existing annotation entry: `otype` is the corrected
    node type, `note` free-text rationale. The converter's original type is
    recorded once as `converted_otype` for provenance. Like `update_manifest`,
    this re-zips + re-uploads the archive and invalidates the local cache.
    """
    if otype is None and note is None:
        raise StorageError("Provide otype and/or note to annotate a node")
    if otype is not None and not otype.strip():
        raise StorageError("otype must be a non-empty string")

    api = _require_api(filename)
    current = api.F.otype.v(node)
    if current is None:
        raise CorpusNotFoundError(f"Node {node} not found in {_safe_name(filename)}")

    cached = _ensure_extracted(filename)
    data = _read_annotations(cached.extract_dir)
    nodes = data.setdefault("nodes", {})
    entry: dict[str, Any] = nodes.get(str(node)) or {}
    entry.setdefault("converted_otype", str(current))
    if otype is not None:
        entry["otype"] = otype.strip()
    if note is not None:
        entry["note"] = note
    entry["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    nodes[str(node)] = entry

    sidecar = cached.extract_dir / _ANNOTATIONS_FILE
    sidecar.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    name = _republish(filename, cached)
    logger.info("Annotated node %s in %s (%s)", node, name, sorted(entry))
    return {"node": int(node), **entry}


# ── Index ─────────────────────────────────────────────────────────────────────


def _section_levels(api: Any) -> list[str]:
    try:
        return list(api.T.sectionTypes)
    except Exception:
        return []


def _build_sections(api: Any) -> dict[str, Any] | None:
    """Top-level section nodes with their immediate child sections, or None."""
    levels = _section_levels(api)
    if not levels:
        return None

    top_type = levels[0]
    child_type = levels[1] if len(levels) > 1 else None
    grandchild_type = levels[2] if len(levels) > 2 else None

    items: list[dict[str, Any]] = []
    for node in api.F.otype.s(top_type):
        child_nodes = list(api.L.d(node, otype=child_type)) if child_type else []
        total = len(child_nodes)
        children = [
            _section_entry(api, child, grandchild_type=grandchild_type)
            for child in child_nodes[:_MAX_CHILDREN]
        ]
        item = _section_entry(api, node, grandchild_type=child_type)
        item["children"] = children
        item["truncated"] = total > _MAX_CHILDREN
        items.append(item)

    return {"levels": levels, "items": items}


def get_index(filename: str) -> dict[str, Any]:
    """Return the archive's toc, section structure, and node-type stats."""
    cached = _ensure_extracted(filename)
    toc_path = cached.extract_dir / "toc.yml"
    toc = yaml.safe_load(toc_path.read_text()) if toc_path.is_file() else None

    api = _load_api(filename)
    if api is None:
        return {"toc": toc, "sections": None, "node_types": []}

    return {
        "toc": toc,
        "sections": _build_sections(api),
        "node_types": _node_type_stats(api),
    }


def get_sections(
    filename: str,
    parent: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Paginated section children under `parent` (or top-level if omitted).

    Used by Structure to load levels deeper than the two-level index without
    treating content passages as the next otype. `parent` is a section ref
    from the index. Lowest-level sections return an empty item list — the
    client should then call ``/content``.
    """
    limit = max(1, min(int(limit), _MAX_SECTION_PAGE))
    offset = max(0, int(offset))

    api = _load_api(filename)
    empty = {
        "parent": parent,
        "levels": [],
        "items": [],
        "total": 0,
        "offset": offset,
        "limit": limit,
        "next_offset": None,
    }
    if api is None:
        return empty

    levels = _section_levels(api)
    if not levels:
        return {**empty, "levels": levels}

    if parent:
        node = _resolve_section_node(api, parent, levels)
        if node is None:
            raise CorpusNotFoundError(
                f"Section reference {parent!r} not found in {_safe_name(filename)}"
            )
        otype = api.F.otype.v(node)
        idx = levels.index(otype) if otype in levels else -1
        child_type = levels[idx + 1] if 0 <= idx < len(levels) - 1 else None
        grandchild_type = levels[idx + 2] if 0 <= idx < len(levels) - 2 else None
        nodes = list(api.L.d(node, otype=child_type)) if child_type else []
    else:
        child_type = levels[0]
        grandchild_type = levels[1] if len(levels) > 1 else None
        nodes = list(api.F.otype.s(child_type))

    total = len(nodes)
    page = nodes[offset : offset + limit]
    next_offset = offset + limit if offset + limit < total else None
    return {
        "parent": parent,
        "levels": levels,
        "items": [
            _section_entry(api, node, grandchild_type=grandchild_type) for node in page
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
    }


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

    passages: list[dict[str, Any]] = []
    for node in page:
        try:
            text = api.T.text(node, fmt=fmt_used) if fmt_used else api.T.text(node)
        except Exception as exc:  # noqa: BLE001 - degrade to empty, don't fail the page
            logger.debug("text() failed for node %s: %s", node, exc)
            text = ""
        # `node` lets clients cherry-pick a passage's graph node (inspect /
        # annotate it) without a second ref->node resolution round-trip.
        passages.append(
            {"node": int(node), "ref": _section_ref(node, api), "text": text}
        )

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
