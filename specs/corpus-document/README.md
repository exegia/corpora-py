# Corpora Corpus Document Specification

Status: **unpublished, reviewable draft 0.4.0**. Owner: Corpora. This directory
is the authoritative logical contract for all Corpora apps. Start with
[v0.4.0/specification.md](v0.4.0/specification.md). Machine-readable normative
shape is [document.schema.json](v0.4.0/document.schema.json); normative graph
rules and persistence rules are in the specification. The executable checker
covers the graph rules identified there; it is not a complete persistence engine.

Text-Fabric and Context Fabric inform the design but do not own this contract.
The [USX adapter assessment](v0.4.0/usx-adapter.md) maps official 3.1.1 source
concepts to this graph and identifies representation and implementation gaps.
The [real-source ingestion report](v0.4.0/experiments/report.md) demonstrates
ordinary plain-document, PDF and EPUB extraction followed by an independent
Corpora mapper, with additional TEI/Text-Fabric checks. Draft 0.4.0 adds general
core positions for empty pages and source milestones; private source text and
projections are excluded from distributable bundles.
The [PDF acceptance policy](v0.4.0/pdf-ingestion-policy.md) requires atomic
whole-document acceptance and rejection of insufficient recovery. The current
real PDF samples are rejected or pending review, never accepted partial corpora.
Two supplied private USX 3.0 archives also have bounded real-source projections.
The existing `docs/architecture/context-fabric/` and
`packages/common/src/common/schemas/context_fabric/v1/` describe a dependency
model and existing implementation evidence, not the target contract. No existing
application storage or API has been migrated by this draft.

## Local verification and distribution

```sh
uv run --no-project --with jsonschema python scripts/check_corpus_document.py
uv run --no-project --with jsonschema python scripts/check_corpus_document.py --bundle /tmp/corpora-document-0.4.0
```

The second command creates a portable specification directory, checker, and
SHA-256 file manifest. Consumers MUST pin an exact spec version, bundle digest
and source revision; validate the hashes before use. A source revision placeholder
in the consumer template must be filled only after a reviewed commit exists.
A mutable branch name or Context Fabric dependency version is not a pin.
Published schema URIs and release hosting remain undecided. URN schema identifiers
are immutable offline identifiers; they do not imply a hosted endpoint.

| Consumer | Intended use | Distribution remaining |
| --- | --- | --- |
| corpora-py | adapters, validation, API boundaries | wire reviewed contract to packaging and CI |
| corpora-supabase | relational constraints and import transactions | fetch pinned bundle; design migrations separately |
| corpora-web | API and reference boundaries | pin bundle; generate types and validate responses |
| corpora-ui | capability-aware reusable readers | pin generated types; add component contract tests |
| corpora-panel | document/query boundaries | pin bundle; language-specific bindings |
| corpora-panel-gpui | native document/query boundaries | pin bundle; Rust bindings and native tests |

Only this repository was edited. The other projects were not inspected or
modified; distribution to them remains outstanding. Generated bindings and
verified bundle copies must carry provenance and must never become independently
editable authorities. CI in each consumer should verify manifest hashes and run
the same valid/invalid corpus fixtures, plus its own binding tests.
