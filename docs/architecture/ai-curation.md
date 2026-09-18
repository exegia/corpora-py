# AI curation implementation

The backend contract is tracked in [#214](https://github.com/exegia/corpora-py/issues/214).
The implementation order agreed on 2026-09-18 is AI curation, then
[canonical references (#237)](https://github.com/exegia/corpora-py/issues/237), then
[desktop conversion (#187)](https://github.com/exegia/corpora-py/issues/187).

## Deliverables

1. [#232: Deterministic validation core](https://github.com/exegia/corpora-py/issues/232).
   Implemented in `corpora_py.ai.validation` and merged via #238.
2. [#233: Authorized validation and suggestions](https://github.com/exegia/corpora-py/issues/233).
   Validation is implemented through HTTP and MCP with caller access, scope membership,
   version/hash checks, and section-feature requirements. Persisted suggestions and
   rejection remain pending #235; authoritative boundary/label comparisons also remain.
3. [#234: Apply, undo, and recovery](https://github.com/exegia/corpora-py/issues/234).
   Record intent in `corpus_changes` before editing; reconcile interrupted writes.
4. [#235: Durable threads and suggestions](https://github.com/exegia/corpora-py/issues/235).
   Supplies owned, pinned conversation state for suggestions and chat. This dependency
   must be available before the corresponding public handlers are enabled.
5. [#236: Streaming chat](https://github.com/exegia/corpora-py/issues/236).
   Integrate provider configuration, cancellation, and authorized curation tools.

## Validation core

`validate_nodes(api, corpus=..., version=..., nodes=..., required_features=...)`
returns the existing `ValidateResponse` shape. The input API must already be loaded
at the requested version, and the caller must authorize and resolve the selected nodes.
The core does not load paths, verify permissions, or interpret a client-supplied scope.

Required features come from trusted corpus schema metadata, keyed by concrete node
type. For example, `{"word": {"lemma": "str"}, "chapter": {"number": "int"}}`.
There are no universal lemma, label, or numbering assumptions. An unloaded required
feature is a configuration error, not evidence that corpus values are missing.

| Rule | Evidence |
|---|---|
| `OTYPE_MISSING` | The selected node lacks a nonblank string type. |
| `OTYPE_SLOT_MISMATCH` | The node's type conflicts with its position relative to `maxSlot`. |
| `OSLOTS_EMPTY` | A structural node has no slot links. |
| `OSLOTS_INVALID` | A structural node links to a non-integer or out-of-range slot. |
| `OSLOTS_UNREADABLE` | The loader cannot return the structural node's slot links. |
| `FEATURE_MISSING` | An explicitly required feature has no value for this node. |
| `FEATURE_TYPE` | An explicitly required feature is not the declared string/integer type. |

These descriptive identifiers are local rules, not claimed TF/RC rule-number mappings.
Structural findings point to a source walker rebuild. Feature findings need an
authoritative correction before they can become suggestions; the core does not mark
them automatically fixable. Boundary drift and label mismatch require additional
source/schema evidence and belong to #233.

This is a check of the loaded representation, not a replacement for archive round-trip
validation. It never clears caches, recompiles a corpus, or writes feature values.
`/ai/validate` and the combined server's `validate_node` MCP tool share the authorized
service described below. The response shapes are unchanged.

Run `uv run pytest tests/corpora_py/test_ai_validation.py tests/corpora_py/test_ai_contract.py`.

## Authorized validation

`POST /ai/validate` accepts the existing `{ "scope": NodeScope }` payload. Set
`scope.corpus` to a flat archive ID (with or without `.corpus`) in the configured
store, or `job:<UUID>` for a conversion result. Display titles, filesystem paths,
URLs, and names merely loaded into the shared CorpusManager are not access grants.
This clarifies the original stub's "loaded corpus name" description; clients using
mock names must supply a storage ID or owned job ID when integrating.

With auth enabled, the request needs a verified JWT identity. Job results require
that exact owner (including rejecting old unowned jobs); unknown and foreign jobs
both return 404. Supabase archive reads use the existing verified-owner prefix;
the configured Hub backend is the deployment's shared publishing library.
`AUTH_REQUIRED=false` retains the existing single-user local behavior. Published
and read-only archives can be validated because this operation never writes them.

Each call downloads/copies an archive into a private temporary directory. Manifest
version, API, and findings come from that one snapshot; neither the global loaded
corpus registry nor the corpus-detail cache is used. The loader may compile caches
in that temporary copy, but the source archive is unchanged.

```json
{
  "scope": {
    "corpus": "mini",
    "version": "v1.0",
    "level": "passage",
    "node_id": 9,
    "node_type": "paragraph",
    "label": "First paragraph"
  }
}
```

Word scope checks one slot; structural scope checks its anchor and embedded nodes.
Section and document scopes must match the declared section hierarchy. Corpus scope
checks every node and must omit node/type/range. A passage range selects same-type
sibling units under the same nearest declared section in **document order**, not an
integer interval of node IDs. Its anchor must be its first unit or a containing node.
Cross-section ranges and mismatched node types return 422 instead of widening the scope.

`v1.0` and `1.0` identify the same version. Other version mismatches return 409 with
the existing top-level `ErrorInfo(code="stale", current_version=...)`. Optional
`content_hash` is `sha256:<hex>` over UTF-8 default-format text for the unique selected
slots in slot order, with no trimming, normalization, or extra separators. A mismatch
also returns 409. Feature-only changes still require version bumps; the later apply
service must compare displaced feature values as well as the text hash.

Required section features and their types come from the loaded `otext` schema. Other
linguistic requirements and source-based boundary/label comparisons are not inferred.
Infrastructure errors return a generic 503; unreadable archives return 422; absent
identity at the service boundary returns 403 (the HTTP middleware normally returns
401 earlier). Suggestions, rejection, apply/undo, and thread endpoints remain stubs.

Run `uv run pytest tests/corpora_py/test_ai_service.py` for HTTP, MCP (including real
ASGI transport), ownership, scope, and stale-selection coverage.
