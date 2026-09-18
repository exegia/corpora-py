# AI curation implementation

The backend contract is tracked in [#214](https://github.com/exegia/corpora-py/issues/214).
The implementation order agreed on 2026-09-18 is AI curation, then
[canonical references (#237)](https://github.com/exegia/corpora-py/issues/237), then
[desktop conversion (#187)](https://github.com/exegia/corpora-py/issues/187).

## Deliverables

1. [#232: Deterministic validation core](https://github.com/exegia/corpora-py/issues/232).
   Implemented in `corpora_py.ai.validation`; public routes remain pending.
2. [#233: Authorized validation and suggestions](https://github.com/exegia/corpora-py/issues/233).
   Resolve caller access, scope membership, versions, and trusted schema requirements
   before sharing the core through HTTP and MCP.
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
`/ai/validate` remains a 501 contract stub until #233 supplies authorization and version
checks. The existing request/response schemas are unchanged.

Run `uv run pytest tests/corpora_py/test_ai_validation.py tests/corpora_py/test_ai_contract.py`.
