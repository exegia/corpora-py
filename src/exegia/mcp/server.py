"""FastMCP server exposing all 11 Context-Fabric corpus tools."""

import argparse
import time
import uuid
from typing import Any

from fastmcp import FastMCP

from exegia.mcp.corpus import corpus_manager

mcp = FastMCP(
    "Context-Fabric",
    instructions=(
        "Query annotated text corpora via Context-Fabric. "
        "Start with describe_corpus() to understand the structure, "
        "then list_features() to see what data is available, "
        "then search() with a template to find patterns, "
        "then get_passages() to read the matching text."
    ),
)

# ── Pagination state ──────────────────────────────────────────────────────────

_cursors: dict[str, dict[str, Any]] = {}
_CURSOR_TTL = 300  # seconds
_MAX_LIMIT = 100


def _purge_expired() -> None:
    now = time.time()
    expired = [k for k, v in _cursors.items() if now - v["ts"] > _CURSOR_TTL]
    for k in expired:
        del _cursors[k]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _section_ref(node: int, api: Any) -> str:
    try:
        parts = api.T.sectionFromNode(node)
        return " ".join(str(p) for p in parts if p is not None)
    except Exception:
        return str(node)


def _feat(api: Any, name: str) -> Any:
    """Return a feature object by name, trying both Fs() and direct attribute."""
    try:
        return api.Fs(name)
    except Exception:
        return getattr(api.F, name, None)


# ── Discovery tools ───────────────────────────────────────────────────────────


@mcp.tool()
def list_corpora() -> str:
    """List all loaded corpora and the currently active one."""
    names = corpus_manager.list_corpora()
    if not names:
        return "No corpora loaded."
    current = corpus_manager.current
    lines = [f"  {'*' if n == current else ' '} {n}" for n in names]
    return "Loaded corpora (* = current):\n" + "\n".join(lines)


@mcp.tool()
def describe_corpus(corpus: str | None = None) -> str:
    """
    Overview of corpus structure: node types with counts and section hierarchy.

    Args:
        corpus: Name of corpus to describe. Defaults to the current corpus.
    """
    api = corpus_manager.get_api(corpus)

    node_types = api.F.otype.freqList()
    type_lines = "\n".join(f"  {ntype:<20} {count:>10,}" for ntype, count in node_types)

    try:
        sections = api.T.sectionTypes
        section_line = " > ".join(sections)
    except Exception:
        section_line = "(unavailable)"

    try:
        feature_count = len(api.TF.features)
    except Exception:
        feature_count = "?"

    return (
        f"Section hierarchy: {section_line}\n"
        f"Total features: {feature_count}\n\n"
        f"Node types:\n{'Type':<22}{'Count':>12}\n{'-'*34}\n{type_lines}"
    )


@mcp.tool()
def list_features(
    node_type: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    corpus: str | None = None,
) -> str:
    """
    Browse available features, with optional filtering.

    Args:
        node_type: Filter to features present on this node type.
        kind:      Filter by feature kind (e.g. "node", "edge").
        limit:     Maximum number of features to return (default 50).
        corpus:    Corpus name. Defaults to current.
    """
    api = corpus_manager.get_api(corpus)

    try:
        all_features: dict[str, Any] = api.TF.features
    except Exception:
        return "Could not retrieve feature list from this corpus."

    names = sorted(all_features.keys())

    if kind:
        names = [n for n in names if getattr(all_features.get(n), "kind", None) == kind]

    if node_type:
        filtered = []
        for name in names:
            feat = _feat(api, name)
            if feat is None:
                continue
            try:
                if next(iter(feat.s()), None) is not None:
                    filtered.append(name)
            except Exception:
                # fall back: include if we can't check
                filtered.append(name)
        names = filtered

    total = len(names)
    names = names[:limit]
    suffix = f"\n(showing {len(names)} of {total})" if total > limit else ""
    return "Features:\n  " + "\n  ".join(names) + suffix


@mcp.tool()
def describe_feature(
    feature: str,
    sample_size: int = 20,
    corpus: str | None = None,
) -> str:
    """
    Detailed information about a feature: metadata, node types, and top values.

    Args:
        feature:     Feature name.
        sample_size: Number of top values to display (default 20).
        corpus:      Corpus name. Defaults to current.
    """
    api = corpus_manager.get_api(corpus)
    feat = _feat(api, feature)
    if feat is None:
        return f"Feature '{feature}' not found."

    meta = getattr(feat, "meta", {}) or {}
    meta_lines = "\n".join(f"  {k}: {v}" for k, v in meta.items()) or "  (none)"

    try:
        freq = feat.freqList(sample_size)
        freq_lines = "\n".join(f"  {v!r:<30} {c:>8,}" for v, c in freq)
    except Exception:
        freq_lines = "  (unavailable)"

    return (
        f"Feature: {feature}\n"
        f"Metadata:\n{meta_lines}\n\n"
        f"Top {sample_size} values (value / count):\n{freq_lines}"
    )


@mcp.tool()
def get_text_formats(corpus: str | None = None) -> str:
    """
    Show available text encoding formats with sample text.

    Args:
        corpus: Corpus name. Defaults to current.
    """
    api = corpus_manager.get_api(corpus)

    try:
        formats: dict[str, Any] = api.T.formats
    except Exception:
        return "Text formats unavailable for this corpus."

    if not formats:
        return "No text formats defined."

    # Sample from the first few words
    try:
        sample_nodes = list(api.F.otype.s("word"))[:3]
    except Exception:
        sample_nodes = []

    lines = []
    for fmt in sorted(formats):
        if sample_nodes:
            try:
                sample = api.T.text(sample_nodes, fmt=fmt)
                lines.append(f"  {fmt}\n    sample: {sample!r}")
            except Exception:
                lines.append(f"  {fmt}")
        else:
            lines.append(f"  {fmt}")

    return "Available text formats:\n" + "\n".join(lines)


# ── Search tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def search(
    template: str,
    return_type: str = "results",
    limit: int = 20,
    fmt: str | None = None,
    corpus: str | None = None,
) -> str:
    """
    Search the corpus using a Context-Fabric query template.

    Template syntax uses indentation for containment and feature conditions:
        verse
          word pos=verb lex=walk[
    or multi-node patterns:
        book
          chapter
            verse
              word

    Args:
        template:    Query template string.
        return_type: One of "results" | "count" | "statistics" | "passages".
        limit:       Max results to return (1-100, default 20).
        fmt:         Text format for "passages" return_type (e.g. "text-orig-full").
        corpus:      Corpus name. Defaults to current.

    Returns a cursor_id in "results" mode for use with search_continue().
    """
    api = corpus_manager.get_api(corpus)
    limit = max(1, min(limit, _MAX_LIMIT))

    try:
        raw = list(api.S.search(template, silent=True))
    except Exception as exc:
        return f"Search error: {exc}"

    total = len(raw)

    if return_type == "count":
        return f"Total results: {total:,}"

    if return_type == "statistics":
        from collections import Counter
        type_counter: Counter[str] = Counter()
        for tup in raw:
            for node in tup:
                type_counter[api.F.otype.v(node)] += 1
        lines = "\n".join(f"  {t:<20} {c:>8,}" for t, c in type_counter.most_common())
        return f"Result statistics (total={total:,}):\n{lines}"

    if return_type == "passages":
        lines = []
        for tup in raw[:limit]:
            node = tup[0]
            ref = _section_ref(node, api)
            text = api.T.text(node, fmt=fmt) if fmt else api.T.text(node)
            lines.append(f"[{ref}] {text}")
        suffix = f"\n\n(showing {len(lines)} of {total})" if total > limit else ""
        return "\n".join(lines) + suffix

    # default: "results" — return node tuples with section refs + cursor
    _purge_expired()
    cursor_id = str(uuid.uuid4())
    _cursors[cursor_id] = {"results": raw, "offset": 0, "ts": time.time()}

    page = raw[:limit]
    _cursors[cursor_id]["offset"] = len(page)

    lines = []
    for i, tup in enumerate(page, 1):
        refs = " | ".join(_section_ref(n, api) for n in tup)
        lines.append(f"  {i:>4}. {refs}")

    header = f"Results: {total:,} total, showing {len(page)}\n"
    footer = f"\ncursor_id: {cursor_id}" if total > limit else ""
    return header + "\n".join(lines) + footer


@mcp.tool()
def search_continue(cursor_id: str, limit: int = 20) -> str:
    """
    Retrieve the next page of results from a previous search() call.

    Args:
        cursor_id: The cursor_id returned by search().
        limit:     How many results to return (1-100, default 20).
    """
    _purge_expired()

    if cursor_id not in _cursors:
        return "Cursor expired or not found. Run search() again."

    entry = _cursors[cursor_id]
    limit = max(1, min(limit, _MAX_LIMIT))
    results: list[Any] = entry["results"]
    offset: int = entry["offset"]

    if offset >= len(results):
        del _cursors[cursor_id]
        return "No more results."

    api = corpus_manager.get_api()
    page = results[offset : offset + limit]
    entry["offset"] = offset + len(page)
    entry["ts"] = time.time()

    lines = []
    for i, tup in enumerate(page, offset + 1):
        refs = " | ".join(_section_ref(n, api) for n in tup)
        lines.append(f"  {i:>4}. {refs}")

    remaining = len(results) - entry["offset"]
    footer = f"\n{remaining} more. cursor_id: {cursor_id}" if remaining > 0 else "\nEnd of results."
    return "\n".join(lines) + footer


@mcp.tool()
def search_csv(
    template: str,
    output_path: str,
    features: list[str] | None = None,
    corpus: str | None = None,
) -> str:
    """
    Run a search and export results to a CSV file.

    Note: Only works when the server is running with stdio transport.

    Args:
        template:    Query template string.
        output_path: Absolute path for the output .csv file.
        features:    Feature names to include as columns. Defaults to common features.
        corpus:      Corpus name. Defaults to current.
    """
    import csv
    from pathlib import Path

    api = corpus_manager.get_api(corpus)

    try:
        raw = list(api.S.search(template, silent=True))
    except Exception as exc:
        return f"Search error: {exc}"

    if not raw:
        return "No results found."

    feat_names = features or ["otype", "lex", "pos", "gloss"]
    out = Path(output_path).expanduser()

    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        header = ["result_index", "slot_index", "node", "section"] + feat_names
        writer.writerow(header)
        for r_idx, tup in enumerate(raw):
            for s_idx, node in enumerate(tup):
                section = _section_ref(node, api)
                vals = []
                for fn in feat_names:
                    f = _feat(api, fn)
                    vals.append(f.v(node) if f else "")
                writer.writerow([r_idx, s_idx, node, section] + vals)

    return f"Exported {len(raw)} results ({sum(len(t) for t in raw)} rows) to {out}"


@mcp.tool()
def search_syntax_guide(section: str | None = None) -> str:
    """
    Documentation for Context-Fabric / Text-Fabric query template syntax.

    Args:
        section: Optional section name ("nodes", "relations", "quantifiers", "examples").
    """
    GUIDE: dict[str, str] = {
        "nodes": """\
Node lines
----------
Each line names a node type, with optional feature conditions:

  word                       # any word
  word lex=happy             # word where lex == "happy"
  word lex~happ              # word where lex matches regex happ
  word pos#verb              # word where pos != "verb"
  word gloss<abc             # word where gloss < "abc" (string compare)
  word freq>100              # word where freq > 100 (numeric)
  word ?lex                  # word where lex is defined (not null)

Indentation signals containment:
  verse
    word pos=verb            # verse containing a verb
""",
        "relations": """\
Relations
---------
Place relation keywords between two node lines (no indentation change):

  word
  <: word        # immediately before (adjacent)
  word
  < word         # before (not necessarily adjacent)
  word
  =: word        # same slot (co-referential)
  word
  || word        # overlap
  node
  -link> node    # edge named "link" from first to second
""",
        "quantifiers": """\
Quantifiers
-----------
  /without/      # no result where sub-template matches
  /where/        # only results where sub-template matches
  /have/         # synonym for /where/
  /with/         # attach extra nodes without affecting result tuples
  /or/           # disjunction of two sub-templates

Example:
  verse
  /without/
    word gloss=sin
  /-/            # verses that contain no word glossed "sin"
""",
        "examples": """\
Examples
--------
# All verbs in Genesis
word pos=verb
  book name=Genesis

# Verses with more than 10 words
verse
  word             # (count constraint not in template — filter in Python)

# Words where lemma starts with "walk"
word lex~^walk

# Adjacent word pairs
word
<: word

# Clause containing both verb and noun
clause
  word pos=verb
  word pos=noun
""",
    }

    ALL = "\n\n".join(f"=== {k.upper()} ===\n{v}" for k, v in GUIDE.items())

    if section:
        key = section.lower()
        if key in GUIDE:
            return GUIDE[key]
        return f"Unknown section '{section}'. Available: {', '.join(GUIDE)}"

    return ALL


# ── Data access tools ─────────────────────────────────────────────────────────


@mcp.tool()
def get_passages(
    references: list[str],
    fmt: str | None = None,
    corpus: str | None = None,
) -> str:
    """
    Retrieve text passages by section reference.

    Args:
        references: List of section references, e.g. ["Genesis 1:1", "John 3:16"].
        fmt:        Text format, e.g. "text-orig-full". Defaults to the corpus default.
        corpus:     Corpus name. Defaults to current.
    """
    api = corpus_manager.get_api(corpus)
    lines = []

    for ref in references[:_MAX_LIMIT]:
        parts = _parse_section_ref(ref, api)
        if parts is None:
            lines.append(f"[{ref}] — could not parse reference")
            continue

        try:
            node = api.T.nodeFromSection(parts)
        except Exception:
            lines.append(f"[{ref}] — section not found")
            continue

        if node is None:
            lines.append(f"[{ref}] — not found in corpus")
            continue

        try:
            text = api.T.text(node, fmt=fmt) if fmt else api.T.text(node)
        except Exception as exc:
            text = f"(text error: {exc})"

        lines.append(f"[{ref}]\n{text}")

    return "\n\n".join(lines) if lines else "No passages found."


def _parse_section_ref(ref: str, api: Any) -> tuple[Any, ...] | None:
    """Parse a human-readable reference like 'Genesis 1:1' into a section tuple."""
    try:
        section_types = api.T.sectionTypes
        n = len(section_types)
    except Exception:
        n = 3  # assume book/chapter/verse

    ref = ref.strip()

    # Try splitting on whitespace + colon
    if ":" in ref:
        head, verse = ref.rsplit(":", 1)
        tokens = head.split()
        if n == 3:
            book = " ".join(tokens[:-1]) if len(tokens) > 1 else tokens[0]
            chapter = tokens[-1] if len(tokens) > 1 else None
            try:
                return (book, int(chapter), int(verse)) if chapter else (book, int(verse))
            except ValueError:
                return None
    else:
        tokens = ref.split()
        if len(tokens) >= 2:
            try:
                last = int(tokens[-1])
                book = " ".join(tokens[:-1])
                return (book, last)
            except ValueError:
                pass
        return (ref,)

    return None


@mcp.tool()
def get_node_features(
    nodes: list[int],
    features: list[str],
    corpus: str | None = None,
) -> str:
    """
    Batch lookup of feature values for a list of node IDs.

    Args:
        nodes:    List of integer node IDs.
        features: Feature names to retrieve.
        corpus:   Corpus name. Defaults to current.
    """
    api = corpus_manager.get_api(corpus)
    nodes = nodes[:_MAX_LIMIT]

    feat_objs = [(name, _feat(api, name)) for name in features]
    missing = [n for n, f in feat_objs if f is None]
    if missing:
        return f"Unknown features: {missing}"

    col_w = 10
    header = f"{'node':>8}  {'section':<20}" + "".join(f"  {n:<{col_w}}" for n in features)
    sep = "-" * len(header)
    rows = [header, sep]

    for node in nodes:
        section = _section_ref(node, api)
        vals = "".join(f"  {str(f.v(node) if f else ''):<{col_w}}" for _, f in feat_objs)
        rows.append(f"{node:>8}  {section:<20}{vals}")

    return "\n".join(rows)


# ── CLI entry point ───────────────────────────────────────────────────────────


def main() -> None:
    """
    Start the Context-Fabric MCP server.

    Usage:
        cf-mcp --corpus /path/to/corpus
        cf-mcp --corpus /path/to/corpus --name BHSA
        cf-mcp --corpus /path/to/corpus --sse 8000
        cf-mcp --corpus /path/to/corpus --http 8000 --host 0.0.0.0
    """
    parser = argparse.ArgumentParser(
        prog="cf-mcp",
        description="Context-Fabric MCP server",
    )
    parser.add_argument(
        "--corpus",
        metavar="PATH",
        action="append",
        dest="corpora",
        help="Path to a corpus directory (may be repeated).",
    )
    parser.add_argument(
        "--name",
        metavar="NAME",
        action="append",
        dest="names",
        help="Name for each corpus (positional match with --corpus).",
    )
    parser.add_argument(
        "--features",
        metavar="FEAT",
        nargs="+",
        help="Load only these features (default: all).",
    )
    parser.add_argument(
        "--sse",
        metavar="PORT",
        type=int,
        help="Run with SSE transport on this port.",
    )
    parser.add_argument(
        "--http",
        metavar="PORT",
        type=int,
        help="Run with streamable HTTP transport on this port.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for SSE/HTTP transports (default: 127.0.0.1).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    if args.corpora:
        names = args.names or []
        for i, path in enumerate(args.corpora):
            name = names[i] if i < len(names) else None
            corpus_manager.load(path, name=name, features=args.features)

    if args.sse:
        mcp.run(transport="sse", host=args.host, port=args.sse)
    elif args.http:
        mcp.run(transport="http", host=args.host, port=args.http)
    else:
        mcp.run(transport="stdio")
