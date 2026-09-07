---
title: Reference forms — which string is canonical for the UI
description: Decision record reconciling the tfref citation string, the compact positional token (inter-corpus-refs.md) and the Context Fabric canonical Reference (03-references.md).
tags:
  - architecture
  - references
  - context-fabric
status: accepted
type: decision
---

# Reference forms — which string is canonical for the UI

Three ways of naming a node exist in this repo. This record picks one as **the citation string** the UI shows, stores and resolves, and pins the role of the other two, so no component has to guess.

| Form | Example | Spec | Implemented against |
| --- | --- | --- | --- |
| **tfref short form** (+ `urn:tf:` twin) | `bhsa@2021/Deut:4:2!clause1` | [skills/tf-reference-id](../../skills/tf-reference-id/references/grammar.md) · `common.utils.tfref` | every Text-Fabric corpus the pipeline produces, today (`/refs`, `reference_*` / `corpus_reference_*` tools) |
| **Compact positional token** | `cobhsa_bk005_ch004_pa002_cl001` | [inter-corpus-refs.md](./inter-corpus-refs.md) · `common.utils.refcompact` | same corpora; emitted as `token` beside every reference, accepted by `/refs/resolve` |
| **Canonical Reference** | `bible/DEU/4/2/clause-1` | [context-fabric/03-references.md](./context-fabric/03-references.md) | the Context Fabric v1 graph (`admin.ingest`), not the TF pipeline; no resolver in this repo yet |

## Decision

1. **The tfref short form is the canonical citation string for the UI.** It is what `POST /refs` returns, what a pill copies, what a share link carries, what annotations and notes should store. It is the only form that resolves against what the converters emit today, and it is human-legible without a registry.
2. **The compact token is a serialization of the same resolved node**, never a second citation. It exists for places a citation string cannot go: URL fragments, filenames, annotation bodies where `:`/`!`/`@` are hostile, and cross-corpus pointers that must be a single `[a-z0-9_-]` token. It is produced *from* a node and translated *back* through the corpus (`token` on every `/refs` payload; `/refs/resolve?ref=co…` accepts it). Nobody hand-writes one.
3. **The canonical Reference of 03 remains the long-term, edition-independent address** — the thing that lets a KJV verse and a BHSA verse be "the same" verse. It is not in competition with tfref: a tfref string is the `kind: "edition"` special case of it, expressed over Text-Fabric section headings instead of registry codes. When the converters start emitting `code` / `refOrdinal` and an alias registry exists, tfref's section values become codes with **no grammar change** (`bhsa@2021/DEU:4:2!clause1`) and the 03 resolver can translate both ways.

## Why tfref and not the others

- **Resolvable now.** The canonical form needs `structureProfile`, `code`, `refOrdinal` and alias tables that nothing in `admin.converters` produces; the Text-Fabric pipeline has section headings and node order, which is exactly what tfref consumes.
- **Stable enough, and honest about when it is not.** Sub-unit ordinals shift between corpus builds; tfref makes that explicit by always emitting `@version` and refusing (409) a version it does not have loaded. The compact form has the same fragility with no version slot, which is the strongest reason not to make it the citation.
- **Schema-agnostic.** Section path depth comes from `T.sectionTypes`; the same grammar addresses `book:chapter:verse` and `volume:chapter:paragraph`. The compact form needs a fixed prefix vocabulary (`bk/ch/pa`) and the canonical form needs a scheme registry entry per hierarchy.
- **Headings are not display labels here.** 03 forbids resolving through labels. In Text-Fabric the section *features* (`book`, `chapter`, `verse`) are the corpus's declared addressing keys — the same role `code`/`refOrdinal` play in 03 — so tfref does not violate that rule, it applies it to the data model that exists.

## How the forms map

Every form names the same node through the same numbers. The sub-unit ordinal in all three is "1-based position among nodes of that type that **start** in the section" (tfref's anchor-to-first-slot rule; 03 §3.1 "counts under the nearest present ancestor"; inter-corpus-refs "Skipping levels"). `common.utils.refcompact` reuses `tfref.Adapter.children` for the count, so tfref and the token cannot disagree.

```text
tfref      bhsa@2021/Deut:4:2!clause1
token      cobhsa_bk005_ch004_pa002_cl001        (Deut is the 5th book; headings → ordinals)
canonical  bible/DEU/4/2/clause-1  kind: edition, editionSlug: bhsa   (future; codes from a registry)
```

| Concept | tfref | compact | canonical (03) |
| --- | --- | --- | --- |
| corpus | `corpus` id (library stem / loaded name) | `co<slug>` (`_`→`-`) | `editionSlug` |
| version | `@version` (optional in, emitted out) | — (not encoded; see amendments) | edition is versioned by id |
| section levels | heading values, `:`-joined, depth ≤ `len(T.sectionTypes)` | `bk`/`ch`/`pa` ordinals by depth | `code` / `refOrdinal` per `structureProfile` level |
| sub-unit | `!<otype><i>[-<j>]` | `st`/`cl`/`ph`/`wo`(+`pa` as block on shallow corpora) `NNN[-NNN]` | `sentence-N` / `clause-N` / `word-N` |
| skipped level | not expressible (always full path to the anchor section) | allowed, counts under nearest present ancestor | allowed, same rule |
| ranges | inclusive, same otype, same anchor | same, innermost unit only | start/end Reference pair |

## Amendments this decision makes to inter-corpus-refs.md

Recorded here and applied in `common.utils.refcompact`; the spec's "Open issues" are updated to point at them.

1. **Corpus id is the library slug** (`cobhsa`, `comoby-dick`), not a 4-hex UUID tail — the spec's own recommendation in open issue 1. `_` in a library name folds to `-` because `_` is the level separator; the resolver tries both spellings.
2. **Prefixes bind by section depth**, not by type name: 1st `T.sectionTypes` level = `bk`, 2nd = `ch`, 3rd = `pa`. `pa` additionally names the block-level node type (`paragraph`/`para`/`verse`) under the innermost section when the corpus has fewer than three section levels — which is what this repo's converters emit (`book` over `paragraph`). Open issue 4 is thereby decided: one prefix, resolved by corpus shape.
3. **`ph` (phrase) is added** to the sub-unit set; BHSA has phrases between clause and word.
4. **Ranges** `wo003-005` are allowed on the innermost unit, mirroring tfref.
5. **No version slot.** A token is only valid against the corpus build that produced it; anything that needs durability stores the tfref string (which carries `@version`) and derives the token on demand.

## Consequences

- UI: render `label` / `compact` from `/refs/shortcode`, copy `ref`, link with `url`; use `token` only where a bare identifier is required (fragment, file name, annotation key). Never show a token as the citation.
- Storage: persist `ref` (tfref). If a token is persisted anywhere, persist the corpus version next to it.
- Roadmap: when `admin.ingest` (Context Fabric graph) and the TF pipeline converge, implement the 03 resolver and a `tfref ↔ canonical` translation; the tfref grammar does not change.
