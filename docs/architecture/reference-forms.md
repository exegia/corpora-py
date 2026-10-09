---
title: Reference forms — CUSX canonical citations and durable links
description: Separate USX-style canonical citation, revision-pinned CUSX endpoint, display label and legacy Text-Fabric forms.
tags:
  - architecture
  - references
  - cusx
status: proposed
type: decision
---

# Reference forms — CUSX canonical citations and durable links

**Design update, 2026-10-05.** The target publication format is CUSX. This record
supersedes the previous design decision that tfref would remain the long-term
canonical UI citation. The existing TF APIs still emit and resolve tfref today;
no runtime behavior is changed by this record. The detailed target contract is
[inter-corpus-refs.md](./inter-corpus-refs.md).

## Decision

1. **Canonical scripture citations follow USX's familiar address shape.** Examples:
   `MAT 3:1-4`, `QUR 2:255`, `1NE 3:7`. Store profile and numbering scheme/version
   alongside the string; Quran references also retain the declared reading.
2. **Durable cross-corpus links name exact CUSX endpoints.** Use package identity,
   immutable package revision, document ID and optional anchor ID. A word, clause,
   paragraph or other node may target any other node; types need not match.
3. **Fine-grained boundaries belong to an edition and analysis.** Use existing
   CUSX span anchors or paired `cx:boundary` ranges. Ordinals are scoped selectors,
   not identity. Paragraphs and verses remain separate axes.
4. **Display and compatibility forms remain separate.** Labels are presentation.
   tfref/compact tokens continue to serve TF APIs and require an explicit pinned
   conversion mapping before they can identify a CUSX target.

## Forms and examples

| Form | Example | Role |
| --- | --- | --- |
| USX-style canonical address | `MAT 3:1-4` | Citation under `bible` plus explicit numbering context |
| Quran adaptation | `QUR 2:255` | Citation under `quran`, reading and ayah-numbering context |
| Book of Mormon adaptation | `1NE 3:7` | Citation under `book-of-mormon` and its code/numbering registry |
| CUSX endpoint URI | `x-corpora:/greek-nt/1/luke#word-a7` | Exact revision-pinned word/range target |
| Local CUSX link | `luke.usx#word-a7` | Package-local serialization; pin before durable storage |
| TF compatibility citation | `bhsa@2021/Deut:4:2!clause1` | Existing TF resolver input/output |
| Compact TF token | `cobhsa_bk005_ch004_pa002_cl001` | Derived positional token for its source build |
| Historical Context Fabric path | `bible/DEU/4/2/clause-1` | Previous graph proposal; explicit adapter required |

The [USX linking rules](https://ubsicap.github.io/usx/usx3.0.3/linking.html) use
`link-href` for destinations and `link-id` for anchors. `x-corpora` is our extension
scheme; Quran and Book of Mormon code registries are also Corpora proposals, not
upstream USX standards. See the detailed contract for URI encoding, profile codes,
range grammar and concrete XML examples.

## What storage keeps

A link record keeps independently scoped source and target endpoints. The
source may identify a word, paragraph, paired clause range or point in one
publication; the target may have a different type in another publication.

```json
{
  "source": {"packageId": "study-book", "revision": "1", "documentId": "chapter-a", "anchorId": "paragraph-k4"},
  "target": {"packageId": "greek-nt", "revision": "1", "documentId": "luke", "anchorId": "word-a7"},
  "targetUri": "x-corpora:/greek-nt/1/luke#word-a7",
  "relationType": "cross-reference",
  "status": "resolved"
}
```

This example is a proposed link record, not a claim that those packages exist.
`resolved` is assigned only after exact target verification. Typed assertions
such as quotation or translation alignment additionally carry attribution and
evidence. The target URI is derived from the endpoint fields and must agree with
them. Optional canonical citation fields preserve profile, numbering/version,
reading and original `loc`; they are not substituted for exact node identity.
An unresolved/unavailable reference retains its original request and diagnostics.

Imported anchor IDs can be revision-local. A publisher wishing to preserve an
anchor across revisions must retain allocated identity and verify its unchanged
meaning; clients never assume that `anchor-1` survives a new build. Repository
scope binds metadata revision to the package checksum. Changing content under
the same identity/revision is rejected. CUSX syntax version `0.1.0` is not a text
revision and must not be used as one.

## UI and resolution behavior

Show a friendly label and canonical citation when available. Copy an exact CUSX
URI for a durable fine-grained link. Verse-level citation requests may remain
work-level until an edition is selected; word/clause/paragraph requests always
pin a concrete revision and segmentation scheme. Do not manufacture a chapter,
verse or analysis for ordinary prose to obtain a reference string.

Resolution has four outcomes: `resolved`, `ambiguous`, `unresolved`, `unavailable`.
There is no successful fallback from an absent word to its containing verse,
from an unavailable revision to latest, or from one numbering scheme to another.
Targets spanning multiple blocks retain their full declared range. Cross-edition
alignment is explicit, attributed evidence rather than ordinal equality.

## Current implementation boundary

| Layer | Current behavior | Work still required |
| --- | --- | --- |
| TF API | tfref and compact token supported | Preserve compatibility; bridge only with pinned external mapping |
| CUSX content | `link-id`, `cx:id`, spans and boundary axes supported | Allocate/advertise anchors for every supplied fine-grained target |
| CUSX package validation | Local inventory/anchor links checked; URI links not certified | Load exact external scope and verify complete target extent |
| Canonical citation | Source `loc`, profile and numbering fields available | Implement scoped Bible/Quran/Book of Mormon registries and resolver |
| Persistence/UI | Existing TF behavior remains in place | Adopt separate endpoint/citation/label fields when resolver is ready |

The Context Fabric reference documents describe the earlier graph design and do
not override this CUSX target proposal. No runtime schemas, APIs, exporters,
published packages or prior SQL artifacts are modified by this decision update.
