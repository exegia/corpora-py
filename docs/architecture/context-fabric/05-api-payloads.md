---
title: 05 — API Payloads
description: Response envelopes, worked payloads, normative client-consumption rules.
type: spec
tags:
  - architecture
  - context-fabric
---

# 05 — API Payloads

This document specifies the response envelopes that Context Fabric servers hand to client applications — the four top-level shapes (`NodeResponse`, `RangeResponse`, `ResolveResponse`, `SearchResponse`), the `NodePayload` denormalization they all carry, and the normative rules a client must follow to consume them safely. The machine-readable contract is [`api-payloads.schema.json`](../../../packages/common/src/common/schemas/context_fabric/v1/api-payloads.schema.json); the six worked examples below are copied from the CI-validated fixtures in [`examples/index.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/index.json) and are normative.

See also: [README](README.md) · [01 Domain Model](01-domain-model.md) · [02 Node Taxonomy](02-node-taxonomy.md) · [03 References](03-references.md) · [04 Physical Location](04-physical-location.md) · [06 Queries & Storage](06-queries-and-storage.md) · [07 Migration Mapping](07-migration-mapping.md) · [08 Invariants & Versioning](08-invariants-and-versioning.md)

---

## 1. Envelope conventions

### 1.1 `schemaVersion` everywhere

Every envelope — and every entity nested inside one — carries `schemaVersion` (semver, e.g. `"1.0.0"`). The major version also appears in the schema `$id` path (`/v1/`). Clients pin on the major; minors add optional fields only (see §3.6).

### 1.2 The four envelopes

A response document validates against **exactly one** of the four envelopes (the schema root is a `oneOf`):

| Envelope | Shape | Used when |
|---|---|---|
| `NodeResponse` | `{ schemaVersion, node, breadcrumbs?, prev?, next? }` | One node in full, with ancestry and adjacent reading units. The reader-view workhorse. |
| `RangeResponse` | `{ schemaVersion, ref?, nodes[], total, offset?, limit?, nextCursor? }` | An ordered run of nodes: a passage range, a page of reading units, search-result expansion. |
| `ResolveResponse` | `{ schemaVersion, input, status, reference?, matches[] }` | Resolving a canonical reference string (`"bible/JHN/3/16"`) to concrete node ids. `status` ∈ `resolved / partial / ambiguous / not_found`. |
| `SearchResponse` | `{ schemaVersion, query, hits[], total, nextCursor? }` | Full-text / structural search. Hits carry `nodeId`, `editionId`, `score`, `snippet` (highlights as `<em>…</em>`), and a `ref`. |

`ResolveResponse` and `SearchResponse` deliberately return **pointers** (`nodeId` + `editionId` + `ref`), not payloads — the client follows up with a node or range fetch. This keeps resolution and search cheap and lets the client choose its own expansion.

### 1.3 `NodePayload` — the denormalized node

`NodePayload` is a `ContentNode` ([schema](../../../packages/common/src/common/schemas/context_fabric/v1/content-node.schema.json)) extended for display with:

| Field | Meaning |
|---|---|
| `fragments[]` | Inline [`TextFragment`](../../../packages/common/src/common/schemas/context_fabric/v1/text-fragment.schema.json)s, in `ordinal` order. Absent/empty for non-text-bearing nodes **and** for container nodes served shallow. |
| `text` | Convenience concatenation of fragments (`text` + `after`). Redundant with `fragments`; provided for simple clients. |
| `children[]` | Inline child payloads (recursive) **only when the request asked for expansion**. Otherwise omitted — use `childCount` plus a descendants query. |
| `ref` | The node's canonical [`Reference`](../../../packages/common/src/common/schemas/context_fabric/v1/reference.schema.json). |
| `annotations[]` | Standoff [`Annotation`](../../../packages/common/src/common/schemas/context_fabric/v1/annotation.schema.json)s attached to this node or its fragments. |

`NavItem` is the lightweight sibling of `NodePayload` used in `breadcrumbs` / `prev` / `next`: `{ id, category, type, label?, code?, refOrdinal?, ref? }` — enough to render a link and fetch the node, nothing more.

### 1.4 Expansion knobs

Routes in this doc are **illustrative REST** — the envelopes are the contract, the paths are not. A server is conformant if its responses validate against the envelope schemas, whatever its URL design.

- **Shallow (default)** — a container node comes back with `childCount` set, no `children`, and no `fragments` (containers served shallow omit fragment inlining even if descendants carry text).
- **`?expand=children`** — inline `children` recursively; servers SHOULD cap depth (`&depth=2`) and fall back to shallow beyond the cap.
- **`?expand=annotations`** — attach `annotations` to each payload (on the node whose subtree anchors them).
- Leaf, text-bearing nodes always include `fragments` and `text`.

### 1.5 Pagination

`RangeResponse` and `SearchResponse` paginate with `nextCursor` — an **opaque keyset cursor**; `null` means the run is exhausted. `total`/`offset`/`limit` are informative (progress bars, "n of m"); clients MUST NOT compute their own offsets to skip ahead, because keyset cursors are position-stable and offsets are not. The cursor maps to a `(edition_id, path)` keyset in storage — see [06 §1.4](06-queries-and-storage.md).

### 1.6 Relationship to the existing repo surface

The shipped Hub detail API (`GET /storage/{filename}/index` and `/content` in [`corpus_detail_api.py`](../../../packages/admin/src/admin/services/corpus_detail_api.py), returning `{ref, format, passages[{ref,text}], total, offset, limit, next_offset}`) is the predecessor of `RangeResponse` and keeps working unchanged. These envelopes are the contract **now**; the HTTP surface adopts them in a later phase ([07](07-migration-mapping.md)).

---

## 2. Six worked examples

Each fixture is CI-validated against the envelope named in [`examples/index.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/index.json). Excerpts below are copied verbatim from the fixture, elided with `…`.

### 2.1 Scripture verse — `NodeResponse`

A reader shows John 3:16 in the KJV with a breadcrumb trail and verse-to-verse navigation.

```http
GET /v1/editions/018f0000-…-0e01/nodes/018f0000-…-0103        (illustrative)
GET /v1/resolve?ref=bible/JHN/3/16&edition=kjv                 (how the id was found)
```

```json
{
  "schemaVersion": "1.0.0",
  "node": {
    "id": "018f0000-0000-7000-8000-000000000103",
    "category": "block",
    "type": "bible:verse",
    "refOrdinal": 16,
    "label": "16",
    …
    "text": "For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.",
    "ref": {
      "scheme": "bible",
      "kind": "canonical",
      …
      "canonical": "bible/JHN/3/16",
      "display": "John 3:16 (KJV)"
    }
  },
  "breadcrumbs": [ … ],
  "prev": { "id": "018f0000-0000-7000-8000-000000000104", "category": "block", "type": "bible:verse", "label": "15", "refOrdinal": 15 },
  "next": { … }
}
```

Demonstrates: **canonical reference** (`kind: "canonical"`, code-addressed book + ordinal chapter/verse), **breadcrumbs** (book → chapter `NavItem`s, outermost first), **prev/next** reading units at the verse level. Full fixture: [`scripture-node.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/scripture-node.json).

### 2.2 Book chapter paragraph — `NodeResponse`

A monograph paragraph addressed purely by generic hierarchy — no domain scheme, just chapter/section/paragraph ordinals.

```http
GET /v1/resolve?ref=monograph/chapter-4/section-2/paragraph-3   (illustrative)
GET /v1/editions/{editionId}/nodes/{nodeId}
```

```json
{
  "schemaVersion": "1.0.0",
  "node": {
    …
    "category": "block",
    "type": "generic:paragraph",
    "refOrdinal": 3,
    …
    "ref": {
      "scheme": "monograph",
      "kind": "canonical",
      "workSlug": "on-reading-collections",
      "segments": [
        { "levelType": "generic:chapter", "ordinal": 4 },
        { "levelType": "generic:section", "ordinal": 2 },
        { "levelType": "generic:paragraph", "ordinal": 3 }
      ],
      "canonical": "monograph/chapter-4/section-2/paragraph-3",
      "display": "Chapter 4, Section 2, ¶3"
    }
  },
  "breadcrumbs": [ … ]
}
```

Demonstrates: **deep generic hierarchy** — every segment is an ordinal-addressed `generic:*` level, so the canonical string uses the disambiguated `<level>-<ordinal>` token form; breadcrumbs include the `root` node (`generic:book`). Full fixture: [`book-chapter.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/book-chapter.json).

### 2.3 Letter page — `NodeResponse`

An OCR'd 1863 letter: the paragraph is addressed by the **page it sits on**, so the reference is edition-bound, and the payload carries OCR confidence, a correction trail, and a bounding box back into the scan.

```http
GET /v1/resolve?ref=letter/page-2/paragraph-1&edition=scan-1863   (illustrative)
```

```json
{
  "schemaVersion": "1.0.0",
  "node": {
    …
    "type": "letter:paragraph",
    "locators": [ { "sourceAssetId": "018f0002-0000-7000-8000-000000000f01", "pageIndex": 1, "printedLabel": "2" } ],
    "fragments": [
      {
        …
        "confidence": 0.91,
        "locators": [ { …, "bbox": { "x": 96.0, "y": 120.5, "width": 402.0, "height": 88.0, "unit": "pt" } } ]
      }
    ],
    "ref": { "scheme": "letter", "kind": "edition", …, "canonical": "letter/page-2/paragraph-1" },
    "provenance": {
      …
      "validationState": "flagged",
      "corrections": [ { "correctedAt": "2026-07-16T15:00:00Z", "path": "/fragments/0/text", "previousValue": "You ask whether the mannscripts arrived intact.", … } ]
    }
  },
  "prev": null
}
```

Demonstrates: **edition-kind page reference** (`kind: "edition"` — the address depends on this scan's pagination), **OCR confidence** at fragment level, **append-only correction history** in `provenance`, **bbox** locator into the source asset, and `prev: null` at a run boundary. Full fixture: [`letter-page.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/letter-page.json).

### 2.4 Academic paper section — `NodeResponse` with expansion

A paper's §2 fetched with children and annotations inlined — the section itself is a container (no fragments), its paragraph child spans a page break, and its second child is a table node.

```http
GET /v1/editions/{editionId}/nodes/{nodeId}?expand=children,annotations   (illustrative)
```

```json
{
  "schemaVersion": "1.0.0",
  "node": {
    …
    "category": "section",
    "type": "acad:section",
    "heading": "2. Methods",
    "childCount": 2,
    "locators": [ { …, "pageIndex": 2, "printedLabel": "142" }, { …, "pageIndex": 3, "printedLabel": "143" } ],
    "children": [
      {
        …
        "type": "acad:paragraph",
        "fragments": [ { …, "pageIndex": 2 … }, { …, "pageIndex": 3 … } ],
        "annotations": [ { …, "kind": "note:footnote", "marker": "3", "target": { "fragmentId": "018f0003-0000-7000-8000-000000000202" }, … } ]
      },
      { …, "category": "table", "type": "acad:table", "label": "Table 1", … }
    ]
  }
}
```

Demonstrates: **`expand=children`** (recursive `NodePayload`s inline), **annotations** (a footnote targeting one fragment), **table node** (`category: "table"` with a `src/pdf` table model in `ext`), and a **page-spanning section** — two node-level locators, and the paragraph's two fragments each carry their own page locator. Full fixture: [`academic-paper.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/academic-paper.json).

### 2.5 Speech — `NodeResponse`

The Gettysburg Address, first paragraph: one logical node grounded in **two** source assets — the plaintext transcription and the audio recording.

```http
GET /v1/resolve?ref=oratory/paragraph-1&work=gettysburg-address   (illustrative)
```

```json
{
  "schemaVersion": "1.0.0",
  "node": {
    …
    "type": "oratory:paragraph",
    "fragments": [
      {
        …
        "locators": [
          { "sourceAssetId": "018f0004-0000-7000-8000-000000000f01", "charStart": 0, "charEnd": 176 },
          { "sourceAssetId": "018f0004-0000-7000-8000-000000000f02", "timeStart": 0.0, "timeEnd": 21.4 }
        ]
      }
    ],
    …
    "ext": { "oratory": { "delivered": "1863-11-19", "venue": "Gettysburg, Pennsylvania" } }
  }
}
```

Demonstrates: **dual text/audio locators** on a single fragment — char offsets into the text asset, timecodes into the recording — enabling synchronized read-along playback; domain metadata rides in a namespaced `ext` bucket. Full fixture: [`speech.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/speech.json).

### 2.6 Transcript page — `RangeResponse`

The first page of utterances from an oral-history interview: an ordered run with a keyset cursor, speaker identity in `ext`, and per-cue timecodes.

```http
GET /v1/editions/{editionId}/range?level=transcript:utterance&limit=2   (illustrative)
GET …&cursor=b3JkaW5hbC0y                                               (next page)
```

```json
{
  "schemaVersion": "1.0.0",
  "ref": null,
  "nodes": [
    {
      …
      "type": "transcript:utterance",
      "label": "Interviewer",
      …
      "ext": { "transcript": { "speakerId": "S1", "speakerRole": "interviewer" } }
    },
    { …, "label": "Respondent", … }
  ],
  "total": 214,
  "offset": 0,
  "limit": 2,
  "nextCursor": "b3JkaW5hbC0y"
}
```

Demonstrates: **`RangeResponse`** (`ref: null` — a level page, not a ref-driven range), **speaker `ext`** namespace, multi-fragment utterances with per-cue `timeStart`/`timeEnd`/`sourceFragmentId` locators, and an opaque **`nextCursor`**. Full fixture: [`transcript.json`](../../../packages/common/src/common/schemas/context_fabric/v1/examples/transcript.json).

---

## 3. Client-consumption rules (normative)

The key words MUST / MUST NOT / SHOULD are used as in RFC 2119.

### 3.1 Minimum fields to render any node

A client MUST be able to render a node from: `id`, `category`, `type`, `label?`, one of `fragments` | `text` | `children`, and `ref?`. Everything else is enhancement. A payload with none of `fragments`/`text`/`children` is a shallow container — render its `label`/`heading` and offer expansion via `childCount`.

### 3.2 Unknown-type handling

- `type` is an **open** namespaced vocabulary. A client encountering an unknown `type` MUST fall back to rendering by `category` (the closed enum: `root`, `division`, `section`, `heading`, `block`, `inline`, `list`, `table`, `figure`, `media`, `note`, `milestone`) and MUST NOT fail.
- Unknown `ext` namespaces MUST be ignored for rendering but MUST be preserved byte-for-byte on any write-back (`ext` is the single lossless extension bucket; servers round-trip it untouched).

### 3.3 Navigation

- Readers MUST build navigation from `breadcrumbs` + `prev`/`next` (`NavItem`s), not by inferring structure client-side.
- Clients SHOULD consult `childCount` before requesting expansion, and SHOULD paginate rather than expand unbounded subtrees.
- Clients MUST NOT parse `ref.canonical` strings to derive structure — `canonical` is a serialization, deterministically regenerable from the structured fields. Use `ref.segments` (typed `levelType` + `code`/`ordinal`) for anything programmatic.

### 3.4 Citations

Deterministic recipe for a human citation such as `John 3:16 (KJV)`:

1. If `ref.display` is present, use it verbatim — it is the server's preferred rendering.
2. Otherwise compose from `ref.segments` + edition metadata:
   a. Map each segment's `levelType` through the edition's `structureProfile.levels` to a level label; use the segment's `code` (looked up to a display name via the scheme's alias registry, else the code itself) for code-addressed levels and the `ordinal` for ordinal-addressed levels.
   b. Join with the scheme's conventional separators (bible: `Book C:V`; default: `Level N` comma-joined).
   c. Append the edition qualifier — `(editionSlug uppercased or edition title)` — when citing an edition-specific text or when `ref.kind` is `"edition"`.
3. Never build citations from node `label`s along the breadcrumb trail — labels are display-only and language-dependent; references are label-independent by design.

### 3.5 Text assembly

- Node text is the concatenation of its fragments in `ordinal` order, each contributing `text` then `after` (`after` defaults to `""`). This — and only this — is the definition `text` precomputes.
- `text` is convenience only; clients that need offsets, confidence, per-fragment language/script, or physical locators MUST use `fragments`.
- Clients MUST NOT assume fragments exist: non-text-bearing nodes (tables, figures, media, shallow containers) legitimately have none.

### 3.6 Forward compatibility

- Unknown **optional** fields anywhere in a payload MUST be ignored (never rejected), preserving them on write-back where the client echoes entities.
- `NodeCategory` is **frozen within a schema major version**: a v1 client MAY treat an out-of-enum category as impossible (fail loudly in dev, fall back to `block` in production if defensive). New source semantics arrive as new `type` values — which degrade by rule 3.2 — never as new categories.
- Clients pin the schema major (`/v1/`); a `schemaVersion` minor/patch bump MUST NOT change client behavior.
