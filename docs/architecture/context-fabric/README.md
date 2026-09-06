---
title: Context Fabric — Canonical Content Graph & API Contract (v1)
description: Entry point and reading order for the Context Fabric v1 spec series.
type: spec
tags:
  - architecture
  - context-fabric
---

## Context Fabric — Canonical Content Graph & API Contract (v1)

A universal schema for every corpus this platform converts, stores, and serves: religious
scripture (book/chapter/verse, surah/ayah), monographs (chapter/section/paragraph), letters
(page/paragraph), academic papers, speeches, and transcripts — one model, no fixed hierarchy
depth, no tradition's vocabulary hard-coded as universal columns.

**Status:** v1.0.0 — adopted as the documentation contract (Phase 1 of
[07-migration-mapping.md](07-migration-mapping.md)). The machine-readable JSON Schemas are the
source of truth; these docs explain and motivate them.

## The contract in one paragraph

A **Corpus** holds **Works** (abstract creations); each Work is realized by **Editions**
(one language/script/versification each). An Edition owns an ordered tree of **ContentNodes** —
addressable typed nodes of unlimited depth, each carrying a closed rendering `category` and an
open namespaced `type` (`bible:verse`, `quran:ayah`, `generic:paragraph`). Text lives only in
**TextFragments**, which also join logical structure to physical location via embedded
**PhysicalLocators** (page, bbox, char offsets, timecodes) pointing into **SourceAssets**.
Addressing is by **Reference** — typed code/ordinal segments resolved through scheme/alias
registries, never display labels. **Annotations** attach standoff content (footnotes,
cross-refs, media); **Relationships** link anything to anything (supersedes, translation-of,
aligned-with). Everything source-specific survives losslessly in a namespaced `ext` bucket.

## Reading order

| Doc | Spec items | Contents |
|---|---|---|
| [01-domain-model.md](01-domain-model.md) | A, B | Bounded contexts, entity catalog, ER diagram, semantic vs structural nodes, multi-edition model |
| [02-node-taxonomy.md](02-node-taxonomy.md) | D | Category enum, namespaced types, alias registries per tradition and per source format, unknown-type behavior |
| [03-references.md](03-references.md) | E | Reference grammar, scheme registry, alias resolution, worked examples (`bible/JHN/3/16`, `quran/2/255`, …), versification alignment |
| [04-physical-location.md](04-physical-location.md) | F | PhysicalLocator model, nodes spanning pages, pages holding many nodes, timecoded media |
| [05-api-payloads.md](05-api-payloads.md) | G, J | Response envelopes, six worked payloads, normative client-consumption rules |
| [06-queries-and-storage.md](06-queries-and-storage.md) | H, I | Query patterns, hierarchy-storage evaluation, PostgreSQL DDL (ltree), worked SQL |
| [07-migration-mapping.md](07-migration-mapping.md) | grounding | Exact mapping from today's `Unit`/Text-Fabric/`.corpus` pipeline; phased adoption plan |
| [08-invariants-and-versioning.md](08-invariants-and-versioning.md) | K | Invariants, failure cases, schema/parser versioning, compatibility guarantees |
| [../inter-corpus-refs.md](../inter-corpus-refs.md) | draft | Compact positional address (`co0001_bk001_ch001_pa001…`) for cross-corpus pointers; how it relates to canonical References |

## Machine-readable schemas

JSON Schema **Draft 2020-12**, shipped inside the `corpora-common` package so installed parsers
and services can validate against them at runtime:

```shell
packages/common/src/common/schemas/context_fabric/v1/
  common.defs.schema.json      # Id, SemVer, LangTag, Ext, Provenance, NodeCategory, …
  corpus.schema.json            work.schema.json          edition.schema.json
  content-node.schema.json      text-fragment.schema.json physical-locator.schema.json
  reference.schema.json         source-asset.schema.json  annotation.schema.json
  relationship.schema.json      api-payloads.schema.json
  examples/                    # six CI-validated payload fixtures + index.json
```

- `$id` convention: `https://schemas.exegia.co/context-fabric/v1/<file>` — a stable URI
  namespace, resolved **offline** via a `referencing.Registry`; nothing is fetched.
- Every entity schema is strict (`unevaluatedProperties: false`) with exactly one extension
  point: the namespaced `ext` object.
- CI: [tests/common/test_context_fabric_schemas.py](../../../tests/common/test_context_fabric_schemas.py)
  checks every schema against the 2020-12 metaschema and validates every example fixture
  against its envelope. Run with `uv run pytest tests/common/test_context_fabric_schemas.py`.

## Glossary

| Term | Meaning |
|---|---|
| **Work** | Abstract intellectual creation (the Gospel of John), independent of text/translation |
| **Edition** | One concrete realization of a Work (KJV John); owns all its ContentNodes |
| **ContentNode** | One addressable node in an Edition's tree; typed, ordered, unlimited depth |
| **TextFragment** | Contiguous text run of one node; the only text carrier; the logical↔physical join |
| **category** | Closed 12-value rendering class (frozen per schema major) |
| **type** | Open namespaced semantic label (`bible:verse`); unknown values degrade to category |
| **Reference** | Label-independent address: typed segments (code or 1-based ordinal) under a scheme |
| **scheme** | A reference tradition (`bible`, `quran`, `monograph`, `letter`, …) with level sequence + alias registry |
| **structureProfile** | Edition's declaration of which node types are reference levels and how they're addressed |
| **PhysicalLocator** | Coordinate into a SourceAsset: page, printed label, bbox, char offsets, timecodes |
| **ext** | The single lossless namespaced extension bucket (`src/epub`, `tei`, `x-vendor`) |
| **Provenance** | Parser name/version/profile, confidence, validation state, append-only corrections |

## Change process

1. Propose changes by editing the schemas first; the test suite must stay green.
2. Additive optional fields → MINOR bump of `schemaVersion`; anything breaking → new `/v2/`
   directory side-by-side (see [08-invariants-and-versioning.md](08-invariants-and-versioning.md)).
3. Update the affected doc(s) in the same PR; fixtures are normative — extend them when a new
   capability is specced.
