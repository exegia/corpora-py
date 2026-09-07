"""Reference identifiers over stored `.corpus` archives.

One implementation, two surfaces (`reference_api.py` REST, `reference_mcp.py`
MCP), following the `corpus_detail` split. Three operations:

* `create_reference` -- a node (or a same-type node range) the user clicked
  becomes a stable `corpus@version/Sec:...!otypeN` string.
* `resolve_reference` -- a reference string becomes the node(s) it names, plus
  the parent corpus's metadata (title, authors, year, corpusId, ...) so a
  client can render a citation without a second round trip.
* `shortcode` -- the presentation bundle for one reference (label, compact
  pill token, share URL, markdown/html snippets).

The grammar, the anchor-to-first-slot rule and the version rules live in
`common.utils.tfref` (the same file the `skills/tf-reference-id` skill ships).
The corpus id inside a reference is the library filename stem (`bhsa` for
`bhsa.corpus`), because that is the key every other `/storage` surface uses;
the version is the archive manifest's `version`, since converted corpora carry
no `@version` in `otype.tf`.
"""

from __future__ import annotations

import threading
from typing import Any

import yaml
from common.utils import refcompact, refdisplay, tfref
from common.utils.tfref import Adapter, Ref

from .corpus_detail import _ensure_extracted, _require_api, _safe_name, get_manifest

_CORPUS_SUFFIX = ".corpus"
_adapters: dict[str, tuple[int, Adapter]] = {}  # filename -> (id(api), adapter)
_lock = threading.Lock()


def corpus_id_for(filename: str) -> str:
    """`bhsa.corpus` -> `bhsa`: the id a reference carries for this archive."""
    name = _safe_name(filename)
    return name[: -len(_CORPUS_SUFFIX)]


def filename_for(corpus_id: str) -> str:
    return _safe_name(corpus_id)


def _filename_for_slug(slug: str) -> str:
    """A compact token folds `_` to `-`; try the slug as-is, then unfolded."""
    for candidate in (slug, slug.replace("-", "_")):
        try:
            _require_api(candidate)
        except Exception:  # noqa: BLE001 - try the next spelling
            continue
        return _safe_name(candidate)
    return _safe_name(slug)


def _read_toc(filename: str) -> dict[str, Any]:
    cached = _ensure_extracted(filename)
    path = cached.extract_dir / "toc.yml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _adapter(filename: str) -> tuple[Adapter, dict[str, Any], dict[str, Any]]:
    """(adapter, manifest, toc) for `filename`, cached per loaded api object."""
    api = _require_api(filename)
    manifest = get_manifest(filename)
    toc = _read_toc(filename)
    version = str(manifest.get("version") or "") or None
    key = _safe_name(filename)
    with _lock:
        hit = _adapters.get(key)
        if hit is not None and hit[0] == id(api):
            return hit[1], manifest, toc
        adapter = tfref.load_corpus(api, version=version)
        _adapters[key] = (id(api), adapter)
    return adapter, manifest, toc


def corpus_metadata(filename: str) -> dict[str, Any]:
    adapter, manifest, toc = _adapter(filename)
    return refdisplay.corpus_metadata(
        corpus_id=corpus_id_for(filename), manifest=manifest, toc=toc, version=adapter.version
    )


def _token(target: int | list[int], adapter: Adapter, corpus_id: str) -> str | None:
    """Compact token, or None for node types the compact form cannot encode."""
    try:
        return refcompact.to_compact(target, adapter, corpus_id)
    except tfref.RefError:
        return None


def _node_payload(adapter: Adapter, ref: Ref, nodes: int | list[int]) -> dict[str, Any]:
    first = nodes[0] if isinstance(nodes, list) else nodes
    last = nodes[-1] if isinstance(nodes, list) else nodes
    lo, _ = adapter.slots(first)
    _, hi = adapter.slots(last)
    text = adapter.text(first)
    if isinstance(nodes, list) and len(nodes) > 1:
        text = " ".join(t for t in (adapter.text(n) for n in nodes) if t)
    return {
        "node": first,
        "nodes": nodes if isinstance(nodes, list) else [nodes],
        "is_range": isinstance(nodes, list) and len(nodes) > 1,
        "otype": adapter.otype(first),
        "sections": refdisplay.sections_dict(adapter, ref.sections),
        "section_types": list(adapter.section_types),
        "first_slot": lo,
        "last_slot": hi,
        "text": text,
    }


def create_reference(
    filename: str,
    node: int,
    end_node: int | None = None,
    *,
    lang: str | None = None,
) -> dict[str, Any]:
    """Reference for `node` (or the inclusive same-type range `node..end_node`)."""
    adapter, manifest, toc = _adapter(filename)
    corpus_id = corpus_id_for(filename)
    target: int | list[int] = (
        [node, end_node] if end_node is not None and end_node != node else node
    )
    ref_str = tfref.serialize(target, adapter, corpus_id=corpus_id, lang=lang)
    ref = tfref.parse(ref_str)
    nodes = tfref.resolve(ref, adapter, lang=lang)  # expands a range to every node
    payload = _node_payload(adapter, ref, nodes)
    payload.update(
        ref=ref_str,
        urn=ref.urn(),
        token=_token(target, adapter, corpus_id),
        corpus=refdisplay.corpus_metadata(
            corpus_id=corpus_id, manifest=manifest, toc=toc, version=adapter.version
        ),
    )
    return payload


def resolve_reference(
    ref_str: str, filename: str | None = None, *, lang: str | None = None
) -> dict[str, Any]:
    """Node(s) + corpus metadata for a reference. `filename` overrides the
    corpus id embedded in the reference (and is required when there is none).

    Accepts the short form, the `urn:tf:` form, or a compact positional token
    (`co<slug>_bk001_...`); the latter is translated through the corpus first.
    """
    if refcompact.is_compact(ref_str):
        filename = filename or _filename_for_slug(refcompact.slug_of(ref_str))
        _, nodes_c = refcompact.from_compact(ref_str, _adapter(filename)[0])
        created = create_reference(
            filename,
            nodes_c[0] if isinstance(nodes_c, list) else nodes_c,
            nodes_c[-1] if isinstance(nodes_c, list) else None,
            lang=lang,
        )
        created["input"] = ref_str
        return created
    ref = tfref.parse(ref_str)
    if filename is None:
        if not ref.corpus:
            raise tfref.ParseError(
                f"{ref_str!r} names no corpus; pass one explicitly or prefix the reference."
            )
        filename = filename_for(ref.corpus)
    adapter, manifest, toc = _adapter(filename)
    corpus_id = corpus_id_for(filename)
    nodes = tfref.resolve(ref, adapter, lang=lang)
    canonical = tfref.serialize(
        [nodes[0], nodes[-1]] if isinstance(nodes, list) else nodes,
        adapter,
        corpus_id=corpus_id,
        lang=lang,
    )
    payload = _node_payload(adapter, ref, nodes)
    payload.update(
        ref=canonical,
        input=ref_str,
        urn=tfref.parse(canonical).urn(),
        token=_token(
            [nodes[0], nodes[-1]] if isinstance(nodes, list) else nodes, adapter, corpus_id
        ),
        corpus=refdisplay.corpus_metadata(
            corpus_id=corpus_id, manifest=manifest, toc=toc, version=adapter.version
        ),
    )
    return payload


def shortcode(
    ref_str: str | None = None,
    *,
    filename: str | None = None,
    node: int | None = None,
    end_node: int | None = None,
    url_template: str | None = None,
) -> dict[str, Any]:
    """Presentation bundle for a reference given as a string or as a node.

    When a corpus can be loaded the reference is normalised first (version
    filled in, canonical spelling); a bare string with no known corpus is
    formatted as-is so the UI can still render a pill for foreign references.
    """
    token: str | None = None
    if ref_str is None:
        if filename is None or node is None:
            raise tfref.ParseError("shortcode needs either a reference or a corpus + node")
        created = create_reference(filename, node, end_node)
        ref_str, token = created["ref"], created["token"]
    elif refcompact.is_compact(ref_str):
        resolved = resolve_reference(ref_str, filename)
        ref_str, token = resolved["ref"], resolved["token"]
    else:
        ref = tfref.parse(ref_str)
        target = filename or (filename_for(ref.corpus) if ref.corpus else None)
        if target is not None:
            resolved = resolve_reference(ref_str, target)
            ref_str, token = resolved["ref"], resolved["token"]
    ref = tfref.parse(ref_str)
    return refdisplay.shortcode_payload(ref, ref_str, url_template=url_template, token=token)
