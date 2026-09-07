---
title: 02 — Node Taxonomy
description: Category enum, namespaced types, alias registries per tradition and per source format, unknown-type behavior.
type: spec
tags:
  - architecture
  - context-fabric
---

This document specifies the two-axis typing system for ContentNodes in the **Context Fabric canonical content graph, v1**: the closed `category` enum (rendering/query contract, frozen per schema major), the open namespaced `type` grammar, and the alias registries that map each tradition's and each source format's vocabulary onto canonical types. Normative definitions live in the schemas — `NodeCategory` and `NamespacedType` in [common.defs.schema.json](../../../packages/common/src/common/schemas/context_fabric/v1/common.defs.schema.json), their use in [content-node.schema.json](../../../packages/common/src/common/schemas/context_fabric/v1/content-node.schema.json) — this document is the registry the schemas defer to ("namespaces are registered in the taxonomy doc").

See also: [README.md](README.md) · [01-domain-model.md](01-domain-model.md) · [03-references.md](03-references.md) · [04-physical-location.md](04-physical-location.md) · [05-api-payloads.md](05-api-payloads.md) · [06-queries-and-storage.md](06-queries-and-storage.md) · [07-migration-mapping.md](07-migration-mapping.md) · [08-invariants-and-versioning.md](08-invariants-and-versioning.md)

## 1. Design principle: no tradition owns the schema

Corpora span scripture, monographs, letters, papers, speeches, and transcripts. If any one tradition's vocabulary became a universal column — a `verse` field, a `surah` level, a `chapter` enum entry — every other tradition would have to contort into it, and every new tradition would demand a schema change.

Context Fabric instead types every node on **two axes**:

1. **`category`** — a closed enum of 12 values describing *how the node behaves* for rendering and querying. Frozen within a schema major version. This is the only vocabulary clients are required to understand.
2. **`type`** — an open namespaced string (`bible:verse`, `quran:ayah`, `tei:div`, `generic:paragraph`) describing *what the node is* in its tradition or source format. New types cost nothing: no schema change, no client change.

The two axes are independent and both required on every node. A client that has never heard of `quran:ayah` still renders it correctly because its `category` is `block`. A search index that has never heard of `letter:signature` still filters on `category: block`. Tradition-specific behavior (verse-number styling, ayah markers) is a progressive enhancement keyed on `type`.

Everything else a source format knows about a node that doesn't fit these axes goes losslessly into `ext` under a namespaced key (`src/epub`, `tei`, `x-vendor`) and is round-tripped untouched.

## 2. The `category` enum

The 12 values of `NodeCategory`, with the rendering contract a client MUST satisfy when it does not recognize the node's `type`:

| Category | Definition | Rendering contract | Example types |
| --- | --- | --- | --- |
| `root` | The single top node of an edition (`parentId: null`) | Document container: render title/metadata chrome, then children. Never rendered as body content | `generic:book`, `acad:article`, `letter:letter`, `oratory:speech` |
| `division` | Major named/numbered structural division; the backbone of navigation | Table-of-contents entry and navigation unit; start a new nav context; render `label`/`heading` prominently | `bible:book`, `bible:chapter`, `quran:surah`, `generic:part`, `tei:div` |
| `section` | Mid-level grouping inside a division | Titled grouping in reading flow; TOC-eligible at lower priority; render heading then children | `generic:section`, `acad:section`, `letter:opening`, `letter:closing` |
| `heading` | Display heading text | Render as a heading styled by `depth`; contributes no body flow of its own | `generic:heading`, `tei:head` |
| `block` | Flow-level unit of body text — the workhorse category | Render as a block: its fragments in order, then any children. Separate from adjacent blocks | `generic:paragraph`, `bible:verse`, `quran:ayah`, `transcript:utterance` |
| `inline` | Span inside a parent block's flow | Render inline within the parent's text, no line break; unknown inline semantics degrade to plain text | `generic:link`, `generic:emphasis` |
| `list` | Ordered/unordered container of list items | Render as a list; children are the items (blocks) | `generic:list`, `html:ul` mappings |
| `table` | Tabular content | Render as a table (rows/cells are child nodes or `ext` payload); never flatten into paragraph flow | `acad:table`, `generic:table` |
| `figure` | Figure/illustration with optional caption | Render as a boxed non-flow object; resolve image via `locators` → SourceAsset; caption from child/`heading` | `acad:figure`, `generic:figure` |
| `media` | Audio/video/image object | Render an embed/player; media source via `locators` (`timeStart`/`timeEnd` for AV) and SourceAsset | `generic:audio`, `generic:video` |
| `note` | Apparatus content out of the main flow (flow-level notes) | Render out-of-band (footnote area, sidebar, disclosure); MUST NOT interrupt body flow | `acad:footnote`, `generic:endnote` |
| `milestone` | Zero-width marker or physical boundary | Render as a marker/anchor (page break, column break). When the edition's `structureProfile` lists its type, it additionally acts as a navigation container for its children | `phys:page`, `generic:page-break` |

Contract rules:

- The enum is **frozen within a schema major version**. New source semantics go into `type`, never into `category`.
- `label`, `heading`, `code`, `refOrdinal` refine rendering; they never change the category contract.
- A `milestone` node may have children (page-addressed editions parent content under `phys:page` nodes — see [01-domain-model.md](01-domain-model.md) §4); clients must not assume milestones are leaves.

## 3. Namespaced `type` grammar and namespace registration

Grammar (`NamespacedType` in the schema): `^[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*$` — that is, `<namespace>:<local-name>`, both lowercase, kebab/underscore allowed, exactly one colon.

**Namespace = tradition or source format.** Registered v1 namespaces:

| Namespace | Scope | Owner of local names |
| --- | --- | --- |
| `generic` | Tradition-neutral structure (book, chapter, section, paragraph, element…) | This spec |
| `phys` | Physical artifacts promoted to nodes (`phys:page`) | This spec |
| `bible` | Biblical tradition | `bible` alias registry (§4.1) |
| `quran` | Quranic tradition | `quran` alias registry (§4.2) |
| `letter` | Epistolary tradition | §4.4 |
| `acad` | Academic papers | §4.5 |
| `oratory` | Speeches | §4.6 |
| `transcript` | Sessions/interviews/hearings | §4.7 |
| `ling` | Linguistic segmentation below the block: sentence, clause, word | §4.8 |
| `tei` | TEI source vocabulary carried through as-is | TEI element names (§5) |
| `x-*` | Vendor experiments; never canonical | The vendor |

Registration rules:

1. Local names are lowercase kebab-case, singular (`bible:verse`, not `bible:Verses`).
2. A namespace is added by adding an alias-registry section to this document (a docs PR, not a schema change).
3. A local name maps to exactly one `category` in its registry. Producers MUST emit that category with that type.
4. Reuse `generic:*` before minting a tradition type: a tradition type is justified only when references, styling, or tooling need to distinguish it.
5. `x-*` namespaces are legal anywhere a `NamespacedType` is legal but are excluded from reference schemes and alias resolution.

The same grammar governs `Annotation.kind` (`note:footnote`, `ref:crossref`, `media:image`, `user:comment`) and namespaced `Relationship.kind` values.

## 4. Alias registries per tradition

Alias registries serve **reference resolution**: they map the names humans type (in any language or abbreviation convention) to the canonical `code`/`refOrdinal` used in [Reference](../../../packages/common/src/common/schemas/context_fabric/v1/reference.schema.json) segments. Display labels never participate — only registry entries do.

### 4.1 `bible`

Reference hierarchy: `bible:book` (code-addressed, USFM 3.0 book codes) → `bible:chapter` → `bible:verse`.

| Canonical type | Category | Addressed by | Source/display aliases (examples) |
| --- | --- | --- | --- |
| `bible:book` | `division` | `code` (USFM: `GEN`, `PSA`, `JHN`, `ROM`…) | John / Jn / Joh / Johannes / Juan / Jean → `JHN`; Psalms / Ps / Psalm → `PSA` |
| `bible:chapter` | `division` | `ordinal` | "chapter 3", "ch. 3", "cap. 3" → ordinal 3 |
| `bible:verse` | `block` | `ordinal` | "verse 16", "v. 16" → ordinal 16 |

`bible/JHN/3/16` ⇒ segments `[{levelType: bible:book, code: JHN}, {levelType: bible:chapter, ordinal: 3}, {levelType: bible:verse, ordinal: 16}]` (see [examples/scripture-node.json](../../../packages/common/src/common/schemas/context_fabric/v1/examples/scripture-node.json)).

### 4.2 `quran`

Reference hierarchy: `quran:surah` → `quran:ayah`. Surahs are ordinal-addressed; names are aliases, not codes.

| Canonical type | Category | Addressed by | Source/display aliases (examples) |
| --- | --- | --- | --- |
| `quran:surah` | `division` | `ordinal` (1–114) | Al-Fatihah / The Opening → 1; Al-Baqarah / The Cow / البقرة → 2 |
| `quran:ayah` | `block` | `ordinal` | "ayah 255", "verse 255" → ordinal 255 |

Named references to sub-surah content are alias-registry entries resolving to full segment paths: *Ayat al-Kursi* → `quran/2/255` (surah 2, ayah 255). Named refs are a registry feature; the graph itself stores only ordinals.

### 4.3 `monograph` (scheme over `generic:*` types)

General books use `generic:*` types; the `monograph` reference scheme declares which of them are levels.

| Canonical type | Category | Addressed by | Aliases (examples) |
| --- | --- | --- | --- |
| `generic:book` | `root` | — (work/edition scope) | — |
| `generic:part` | `division` | `ordinal` | "Part II" → 2; "Book Two" → 2 |
| `generic:chapter` | `division` | `ordinal` | "Chapter IV", "chap. 4" → 4 |
| `generic:section` | `section` | `ordinal` | "§3", "sec. 3" → 3 |
| `generic:paragraph` | `block` | `ordinal` | "¶2", "para. 2" → 2 |

### 4.4 `epistolary`

Letters cited by internal structure or — for scanned/archival letters — by page (`phys:page` as a reference level; see [examples/letter-page.json](../../../packages/common/src/common/schemas/context_fabric/v1/examples/letter-page.json), scheme `letter`, `letter/page-2/paragraph-1`).

| Canonical type | Category | Addressed by | Aliases (examples) |
| --- | --- | --- | --- |
| `letter:letter` | `root` | — | — |
| `letter:opening` | `section` | — | salutation, greeting |
| `letter:body` | `section` | — | — |
| `letter:closing` | `section` | — | valediction, farewell |
| `letter:paragraph` | `block` | `ordinal` | "¶1" → 1 |
| `letter:signature` | `block` | — | signed, subscription |
| `phys:page` | `milestone` | `ordinal` | "p. 2", "page 2", printed label "2" → 2 |

### 4.5 `academic`

| Canonical type | Category | Addressed by | Aliases (examples) |
| --- | --- | --- | --- |
| `acad:article` | `root` | — | paper, article |
| `acad:abstract` | `section` | — | summary |
| `acad:section` | `section` | `ordinal` | "§2", "Section 2", "2.1" (nested sections nest nodes) |
| `acad:paragraph` | `block` | `ordinal` | — |
| `acad:table` | `table` | `ordinal` | "Table 3" → 3 |
| `acad:figure` | `figure` | `ordinal` | "Fig. 1", "Figure 1" → 1 |
| `acad:footnote` | `note` | `ordinal` | "n. 4", "fn 4" → 4 |

### 4.6 `oratory`

| Canonical type | Category | Addressed by | Aliases (examples) |
| --- | --- | --- | --- |
| `oratory:speech` | `root` | — | address, oration |
| `oratory:paragraph` | `block` | `ordinal` | "¶3" → 3 |

### 4.7 `transcript`

| Canonical type | Category | Addressed by | Aliases (examples) |
| --- | --- | --- | --- |
| `transcript:session` | `root` | `ordinal` | "session 2", "day 2", "hearing 2" → 2 |
| `transcript:utterance` | `block` | `ordinal` | turn, utterance, Q/A exchange number |

`transcript:turn` is an accepted alias of `transcript:utterance`. The speaker is **not** a type or a level: the display name goes in `label` ("Interviewer") and stable speaker identity in `ext` under the `transcript` namespace (`{"transcript": {"speakerId": "S1", "speakerRole": "interviewer"}}`), as in [examples/transcript.json](../../../packages/common/src/common/schemas/context_fabric/v1/examples/transcript.json). Timecodes live in fragment `locators` (`timeStart`/`timeEnd`).

### 4.8 `ling` (sub-block levels, any scheme)

Linguistic segmentation below the `block` level. These are not a tradition: any scheme may append them as optional trailing reference levels (see [03 §3.1](03-references.md)), and an edition opts in by listing them in `structureProfile.levels`. Boundaries belong to one analysis (a BHSA-style syntax layer, one translation's word order), so a reference that reaches a `ling:*` level is always `kind: "edition"`. Rationale and the compact encoding: [Inter-corpus references](../inter-corpus-refs.md).

| Canonical type | Category | Addressed by | Aliases (examples) |
| --- | --- | --- | --- |
| `ling:sentence` | `inline` | `ordinal` | "sentence 2", "s. 2" → 2 |
| `ling:clause` | `inline` | `ordinal` | "clause 1", "cl. 1" → 1 |
| `ling:word` | `inline` | `ordinal` | "word 3", "w. 3" → 3 |

`inline` is the category because each is a span inside its parent block's flow; a client that does not know `ling:*` renders the text unchanged. `refOrdinal` is the 1-based position under the parent node. No current converter in this repo emits these types; they are for linguistic corpora such as BHSA.

## 5. Source-format alias tables (today's converters)

Today's converters (`packages/admin/src/admin/converters/`) map parser `Unit.type` strings to Text-Fabric otypes via each `_{format}_to_tf.py`'s `otype_for()`, plus a `root_type` wrapper node. These tables fix how each existing otype lands in the taxonomy; `ParserInfo.profile` in an entity's provenance names which table applied. The original tag/attrs are preserved in `ext` under `src/<format>`. Doc [07-migration-mapping.md](07-migration-mapping.md) covers the full migration.

### `epub` (`_epub_to_tf.py` — root `book`; otypes `chapter`, `paragraph`, `link`, `element`)

| TF otype | Canonical type | Category | Notes |
| --- | --- | --- | --- |
| `book` (root) | `generic:book` | `root` | Carries document metadata |
| `chapter` | `generic:chapter` | `division` | From spine items |
| `paragraph` | `generic:paragraph` | `block` | From paragraph-class tags |
| `link` | `generic:link` | `inline` | `href` preserved in `ext.src/epub` |
| `element` | `generic:element` | `block` | Catch-all; original tag in `ext.src/epub` |

### `pdf` (`_pdf_to_tf.py` — root `book`; every unit is a `page`)

| TF otype | Canonical type | Category | Notes |
| --- | --- | --- | --- |
| `book` (root) | `generic:book` | `root` | |
| `page` | `phys:page` | `milestone` | Pages are the only structure today, so they enter `structureProfile` as the sole reference level (`refOrdinal` = 1-based page); `pageIndex`/`printedLabel` also recorded as locators |

### `tei` (`_tei_to_tf.py` — root `text`; otypes `div`, `paragraph`, `element`)

| TF otype | Canonical type | Category | Notes |
| --- | --- | --- | --- |
| `text` (root) | `tei:text` | `root` | |
| `div` | `tei:div` | `division` | TEI `@type` (e.g. `div type="chapter"`) preserved in `ext.tei` |
| `paragraph` | `tei:p` | `block` | From TEI `<p>` |
| `element` | `generic:element` | `block` | Any other TEI element; name/attrs in `ext.tei` |

### `html` (`_html_to_tf.py` — root `document`; every unit is `element`)

| TF otype | Canonical type | Category | Notes |
| --- | --- | --- | --- |
| `document` (root) | `generic:document` | `root` | |
| `element` | `generic:element` | `block` | Tag name and attributes preserved in `ext.src/html`; a future converter may refine known tags (`p` → `generic:paragraph`/`block`, `a` → `generic:link`/`inline`, `h1–h6` → `generic:heading`/`heading`) without a schema change — that is the point of the open axis |

### `plain` (`_text_to_tf.py` — root `book`; every unit is a `paragraph`)

| TF otype | Canonical type | Category | Notes |
| --- | --- | --- | --- |
| `book` (root) | `generic:book` | `root` | |
| `paragraph` | `generic:paragraph` | `block` | Blank-line-separated paragraphs |

### `docling` (`admin.ingest.docling_graph` — emits the canonical graph directly, no TF otype step)

The first phase-2 producer ([07-migration-mapping.md](07-migration-mapping.md) §4): Docling parses
PDF/DOCX/PPTX/XLSX/HTML/Markdown/images into a `DoclingDocument`, and `admin.ingest` maps its item
labels straight to canonical nodes. Raw Docling labels, self-refs, list markers, and heading levels
survive in `ext["src/docling"]`; Docling page/bbox provenance lands as `PhysicalLocator`s
(`pageIndex` 0-based, bbox normalized to top-left-origin points) — pages are locators, never nodes.

| Docling item label | Canonical type | Category | Notes |
| --- | --- | --- | --- |
| (document root) | `generic:document` | `root` | |
| `title` | `generic:title` | `heading` | Also becomes the Work/Edition title |
| `section_header` | `generic:section` + `generic:heading` | `section` + `heading` | Headers **fold** into nesting `generic:section` containers by their level; the header text survives as a child heading node |
| `text` / `paragraph` / `handwritten_text` | `generic:paragraph` | `block` | Ordinal-addressed reference level (`monograph` scheme) |
| `list_item` | `generic:list-item` | `block` | Marker/enumerated in `ext` |
| list / ordered-list groups | `generic:list` | `list` | |
| inline groups | `generic:inline` | `inline` | |
| chapter / section / sheet / slide groups | `generic:chapter` / `generic:section` / `generic:sheet` / `generic:slide` | `division`/`section` | Sheets/slides are ordinal reference levels when present |
| `table` / `document_index` | `generic:table` / `generic:index` | `table` | Grid preserved as `generic:table-row` → `generic:table-cell` child nodes (cell text stays searchable) |
| `picture` / `chart` | `generic:figure` / `generic:chart` | `figure` | Captions become child `generic:caption` nodes |
| `caption` | `generic:caption` | `block` | |
| `footnote` | `generic:footnote` | `note` | |
| `code` / `formula` | `generic:code` / `generic:formula` | `block` | Code language in `ext` |
| `reference` | `generic:reference` | `block` | Bibliography entries |
| `page_header` / `page_footer` | `generic:page-header` / `generic:page-footer` | `note` | Furniture layer; skipped unless requested |
| `checkbox_*` | `generic:checkbox` | `block` | |
| anything else | `generic:element` / `generic:group` | `block`/`division` | Raw label always in `ext["src/docling"]` |

## 6. Unknown-type behavior

The open `type` axis only works if unknown values are harmless everywhere:

- **Clients MUST render by `category`** when they do not recognize a node's `type`, applying the §2 contract exactly. They MUST NOT fail, drop the node, or block rendering of siblings/descendants.
- **Servers MUST accept and persist** any `type` matching the `NamespacedType` grammar — including namespaces not registered here — and round-trip it (and `ext`) unchanged. Validation may *warn* on unregistered namespaces; it must not reject them.
- **Reference resolution** ignores unregistered types: a `Reference.segments[].levelType` outside the edition's `structureProfile` and scheme registry resolves to `status: not_found` (or `partial`), never to an error.
- **New categories require a new schema major.** `NodeCategory` is frozen within v1; anything that looks like it needs a 13th category is either a new `type` under an existing category or a v2 discussion.

## 7. Where footnotes, media, tables, and figures go

Two homes exist for "extra" content: standoff [Annotation](../../../packages/common/src/common/schemas/context_fabric/v1/annotation.schema.json)s and ContentNodes with categories `table` / `figure` / `media` / `note`.

**Decision rule — anchored vs flow:**

> If the content is *anchored to a point or span of text* and the base text reads correctly without it, it is an **Annotation**. If the content *occupies its own position in document order* — you would hit it while paging through — it is a **ContentNode**.

| Content | Modeling | Why |
| --- | --- | --- |
| Footnote/endnote marker `†` on a phrase | Annotation `kind: note:footnote`, `target.fragmentId` (+ char offsets via range), `marker: "†"`, body `text` or `nodeId` for rich bodies | Anchored to a span; base text stands alone |
| Translator's/editorial gloss on a verse | Annotation `kind: note:editorial`, `target.nodeId` | Anchored to a node |
| Cross-reference ("cf. John 1:1") | Annotation `kind: ref:crossref`, body `reference` | Anchored; body is a Reference, resolved like any other |
| Inline image decorating a phrase | Annotation `kind: media:image`, body `assetId` | Anchored to a span, not part of flow |
| Numbered figure with caption ("Figure 1") | ContentNode `category: figure` (+ caption child), `refOrdinal` | Sits in flow, is cited, participates in references |
| Data table in a paper | ContentNode `category: table` (e.g. `acad:table`) | Flow-level, addressable ("Table 3") |
| Embedded audio/video segment | ContentNode `category: media`, `locators` with `timeStart`/`timeEnd` | Occupies document order |
| Apparatus block / excursus rendered in the note area but present in source flow | ContentNode `category: note` | Flow-level note: it is *content out of the main flow*, not an anchor on other content |
| Reader comment | Annotation `kind: user:comment` | Never part of the canonical text |

Hybrid case: a flow-level figure that a footnote points at is a ContentNode (`category: figure`), and the pointing footnote is an Annotation whose body references it (`body.nodeId`). Rich annotation bodies reuse the node machinery — `AnnotationBody.nodeId` points at a node subtree — so an elaborate footnote with internal paragraphs is an Annotation whose body is a small ContentNode tree, keeping the base flow clean while losing nothing.
