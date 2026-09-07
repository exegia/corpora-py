"""`reference_*` MCP tools over the corpora `CorpusManager` has loaded.

The runtime twin of `admin.services.reference` (which works on library
archives by filename): here the corpus id in a reference is the name the
corpus was loaded under (`--name BHSA`), the version comes from the dataset's
own `@version` metadata or from a `manifest.yml` sitting next to / above the
dataset directory (an unpacked `.corpus` archive has one), and metadata for the
`corpus` block comes from that same manifest when present.

Grammar and resolution rules: `common.utils.tfref` (shared with the
`skills/tf-reference-id` skill). Presentation: `common.utils.refdisplay`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.utils import refdisplay, tfref
from common.utils.tfref import Adapter
from fastmcp.exceptions import ToolError

from .corpus import corpus_manager

_adapters: dict[str, tuple[int, Adapter]] = {}


def _manifest_near(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(manifest, toc) from the dataset dir or its parent -- the archive layout
    is `<root>/manifest.yml` + `<root>/corpora/*.tf`."""
    for root in (path, path.parent):
        mpath = root / "manifest.yml"
        if mpath.is_file():
            try:
                import yaml  # PyYAML: transitive dep, not guaranteed for corpora-mcp alone
            except ImportError:
                return {}, {}
            try:
                manifest = yaml.safe_load(mpath.read_text()) or {}
            except (OSError, yaml.YAMLError):
                manifest = {}
            toc: dict[str, Any] = {}
            tpath = root / "toc.yml"
            if tpath.is_file():
                try:
                    toc = yaml.safe_load(tpath.read_text()) or {}
                except (OSError, yaml.YAMLError):
                    toc = {}
            return (manifest if isinstance(manifest, dict) else {}), (
                toc if isinstance(toc, dict) else {}
            )
    return {}, {}


def _adapter(corpus: str | None) -> tuple[str, Adapter, dict[str, Any], dict[str, Any]]:
    api = corpus_manager.get_api(corpus)
    name = corpus or corpus_manager.current or ""
    manifest, toc = _manifest_near(corpus_manager.get_path(corpus))
    hit = _adapters.get(name)
    if hit is not None and hit[0] == id(api):
        adapter = hit[1]
    else:
        version = str(manifest.get("version") or "") or None
        adapter = tfref.load_corpus(api, version=version)
        _adapters[name] = (id(api), adapter)
    return name, adapter, manifest, toc


def _payload(
    name: str,
    adapter: Adapter,
    manifest: dict[str, Any],
    toc: dict[str, Any],
    ref_str: str,
    nodes: int | list[int],
) -> dict[str, Any]:
    ref = tfref.parse(ref_str)
    first = nodes[0] if isinstance(nodes, list) else nodes
    last = nodes[-1] if isinstance(nodes, list) else nodes
    lo, _ = adapter.slots(first)
    _, hi = adapter.slots(last)
    text = adapter.text(first)
    if isinstance(nodes, list) and len(nodes) > 1:
        text = " ".join(t for t in (adapter.text(n) for n in nodes) if t)
    return {
        "ref": ref_str,
        "urn": ref.urn(),
        "node": first,
        "nodes": nodes if isinstance(nodes, list) else [nodes],
        "is_range": isinstance(nodes, list) and len(nodes) > 1,
        "otype": adapter.otype(first),
        "sections": refdisplay.sections_dict(adapter, ref.sections),
        "section_types": list(adapter.section_types),
        "first_slot": lo,
        "last_slot": hi,
        "text": text,
        "corpus": refdisplay.corpus_metadata(
            corpus_id=name, manifest=manifest, toc=toc, version=adapter.version
        ),
    }


def create_reference(
    node: int, end_node: int | None = None, corpus: str | None = None, lang: str | None = None
) -> dict[str, Any]:
    name, adapter, manifest, toc = _adapter(corpus)
    target: int | list[int] = (
        [node, end_node] if end_node is not None and end_node != node else node
    )
    ref_str = tfref.serialize(target, adapter, corpus_id=name, lang=lang)
    nodes = tfref.resolve(ref_str, adapter, lang=lang)
    return _payload(name, adapter, manifest, toc, ref_str, nodes)


def resolve_reference(
    ref_str: str, corpus: str | None = None, lang: str | None = None
) -> dict[str, Any]:
    ref = tfref.parse(ref_str)
    target = corpus or ref.corpus
    if target is not None and target not in corpus_manager.list_corpora():
        # A reference for a corpus that isn't loaded under that name: fall
        # back to the current corpus only when the caller did not insist.
        if corpus is not None:
            raise tfref.SectionNotFound(
                f"Corpus {target!r} is not loaded. Loaded: {corpus_manager.list_corpora()}"
            )
        target = None
    name, adapter, manifest, toc = _adapter(target)
    nodes = tfref.resolve(ref, adapter, lang=lang)
    canonical = tfref.serialize(
        [nodes[0], nodes[-1]] if isinstance(nodes, list) else nodes,
        adapter,
        corpus_id=name,
        lang=lang,
    )
    payload = _payload(name, adapter, manifest, toc, canonical, nodes)
    payload["input"] = ref_str
    return payload


def shortcode(
    ref_str: str | None = None,
    *,
    node: int | None = None,
    end_node: int | None = None,
    corpus: str | None = None,
    url_template: str | None = None,
) -> dict[str, Any]:
    if ref_str is None:
        if node is None:
            raise tfref.ParseError("shortcode needs either a reference or a node")
        ref_str = create_reference(node, end_node, corpus)["ref"]
    else:
        try:
            ref_str = resolve_reference(ref_str, corpus)["ref"]
        except tfref.SectionNotFound:
            # Foreign or unloaded corpus: present the string as given.
            pass
    return refdisplay.shortcode_payload(tfref.parse(ref_str), ref_str, url_template=url_template)


def _guard(fn, *args, **kwargs) -> str:
    try:
        result = fn(*args, **kwargs)
    except (tfref.RefError, KeyError, RuntimeError) as exc:
        raise ToolError(str(exc)) from exc
    return json.dumps(result, indent=2, ensure_ascii=False)


def register_reference_tools(mcp: Any) -> None:
    """Register `reference_create`, `reference_resolve`, `reference_shortcode`."""

    @mcp.tool()
    def reference_create(
        node: int, end_node: int | None = None, corpus: str | None = None, lang: str | None = None
    ) -> str:
        """
        Create a stable, shareable reference for a node in a loaded corpus.

        Returns `corpus@version/Sec:...!otypeN`, e.g. `BHSA@2021/Deut:4:2!clause1`:
        the section path comes from the corpus's own section hierarchy, and N is
        the node's 1-based position among nodes of its type that *start* in that
        section (so a clause spilling into the next verse is counted once, in
        the verse where it begins). Section nodes get a bare path.

        Args:
            node:     Node id the user selected.
            end_node: Optional last node of an inclusive same-type range.
            corpus:   Corpus name. Defaults to current.
            lang:     Heading language for multilingual section names.
        """
        return _guard(create_reference, node, end_node, corpus, lang)

    @mcp.tool()
    def reference_resolve(ref: str, corpus: str | None = None, lang: str | None = None) -> str:
        """
        Resolve a reference (short form or `urn:tf:`) to node(s) + corpus metadata.

        Returns node id(s), otype, section values, slot span, text, the canonical
        version-explicit spelling, and a `corpus` block (title, authors, year,
        language, corpusId, version) from the dataset's manifest when it has one.

        Args:
            ref:    Reference string, e.g. "BHSA/Deut:4:2!clause1".
            corpus: Corpus name to resolve against. Defaults to the corpus named
                    in the reference, else the current corpus.
            lang:   Heading language.
        """
        return _guard(resolve_reference, ref, corpus, lang)

    @mcp.tool()
    def reference_shortcode(
        ref: str | None = None,
        node: int | None = None,
        end_node: int | None = None,
        corpus: str | None = None,
        url_template: str | None = None,
    ) -> str:
        """
        Presentation bundle for a reference: label, compact pill, share URL.

        Give either `ref` or `node`. Returns `label` ("Deut 4:2 · clause 1"),
        `compact` ("Deut 4:2 cl1"), `url`, `urn`, and `markdown` / `html`
        snippets ready to paste.

        Args:
            ref:          Reference string to present.
            node:         Node id, when building from a selection.
            end_node:     Optional inclusive range end.
            corpus:       Corpus name. Defaults to current.
            url_template: Share-link template with a `{ref}` placeholder
                          (default: REFERENCE_URL_TEMPLATE).
        """
        return _guard(
            shortcode, ref, node=node, end_node=end_node, corpus=corpus, url_template=url_template
        )
