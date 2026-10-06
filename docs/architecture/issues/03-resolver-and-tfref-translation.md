---
title: "Issue draft: 03 resolver + tfref ↔ canonical translation"
description: Implement the Context Fabric canonical Reference resolver (03-references.md) and a lossless tfref ↔ canonical translation, gated on the converters emitting code / refOrdinal.
type: issue-draft
status: proposed
tags:
  - references
  - context-fabric
  - epic
---

> Paste into GitHub as one epic with the three checklists as child issues. Labels: `epic`, `references`, `context-fabric`. Depends on nothing merged after v4.0.0 (#225).

# 03 resolver + tfref ↔ canonical translation once converters emit `code` / `refOrdinal`

## Context

[reference-forms.md](../reference-forms.md) settled the three forms: the **tfref** short form (`bhsa@2021/Deut:4:2!clause1`) is the UI citation, the **compact token** (`cobhsa_bk005_ch004_pa002_cl001`) is its serialization, and the **canonical Reference** of [03-references.md](../context-fabric/03-references.md) (`bible/DEU/4/2/clause-1`) is the edition-independent address with **no resolver in the repo**. tfref is the `kind: "edition"` case of 03 expressed over Text-Fabric section headings; the grammar does not change when headings become registry codes.

What exists today:

- `admin.ingest.docling_graph._assign_reference_levels` already sets `refOrdinal` and an edition `structureProfile` on the Context Fabric graph — but only for `generic:sheet|slide|chapter|section|paragraph`, all `addressedBy: ordinal`; nothing emits `code`, and nothing declares a `scheme`.
- The Text-Fabric walker (`admin.converters._walker.SectionSpec`) emits section **label** features (`book`, `chapter`, `title`, …) only; no `code`, no `refOrdinal`, so a TF corpus cannot answer a canonical reference.
- `reference.schema.json`, `edition.schema.json` (`structureProfile`), `content-node.schema.json` (`code`, `refOrdinal`) are final; the resolver contract (`ResolveResponse.status ∈ resolved|partial|ambiguous|not_found`) is in `api-payloads.schema.json`.
- `common.utils.tfref` (`Adapter`, `children`, anchor-to-first-slot) is the counting engine both existing forms share; the 03 `ling:*` levels use the same "under the nearest present ancestor" rule, so the resolver can reuse it.

## Goal

A client can send `bible/DEU/4/2/clause-1` (or `Bible/BHSA/Deuteronomy/4/2/clause-1`) and get the same node `bhsa@2021/Deut:4:2!clause1` resolves to, with 03's status semantics; and any `/refs` payload can carry its canonical string next to `ref` and `token`.

## Scope — three workstreams

### A. Converters emit the addressing components (prerequisite)

- [ ] `_walker.SectionSpec` gains optional `codes: tuple[str | None, ...]` per level; when a level is code-addressed the walker writes a `code` node feature (e.g. `DEU`) beside the label feature. Source of codes for Bible corpora: an OSIS/Paratext book-code table keyed by the corpus's own book labels and `book@<lang>` aliases (BHSA ships `book@en`, `book@la`, … features — use them as the alias seed).
- [ ] The walker writes `refOrdinal` (1-based, per parent, canonical numbering) for every section level and for `ling:*` types when present (`sentence`, `clause`, `phrase`, `word` — reuse `tfref.Adapter.children` numbering so `refOrdinal` == the `!clauseN` index by construction).
- [ ] `convert_to_corpus` writes a `scheme` + `structureProfile` block into `manifest.yml` (`bible` for `category=bible`, `monograph` for EPUB/PDF/TEI books, `epistolary` for letters), levels listed outermost first with `addressedBy`. Unknown → `generic` scheme, ordinals only.
- [ ] `docling_graph` emits `code` for `bible:book` when the ingest source is scripture, and declares `scheme` on the edition — today it never does.
- [ ] `tf_validate.py` (text-fabric-validator skill) gets a rule: a code-addressed level whose nodes lack `code`, or any level with non-contiguous `refOrdinal`, is a `warn`.

### B. Scheme registry + 03 resolver

- [ ] `common/utils/refscheme.py`: registry data (`bible`, `quran`, `monograph`, `epistolary`, `academic`, `oratory`, `transcript`) with level sequence, `addressedBy`, token style, and alias tables (multilingual, NFKD-folded, casefolded). Bible book aliases: OSIS codes + English/Latin/German/French names + common abbreviations; ambiguous entries (`Jo` → `JHN`/`JOL`) kept so `ambiguous` is testable.
- [ ] `common/utils/canonref.py`: `parse(str) -> Reference` (EBNF §2.1, disambiguation §2.3), `serialize(Reference) -> str`, JSON form per `reference.schema.json`; rejects `ling:*` segments with `kind: canonical` (§3.1).
- [ ] Resolver over a `tfref.Adapter`: walk `structureProfile` levels, match `code` / `refOrdinal` features, then `ling:*` via `Adapter.children`; return `ResolveResponse` with `resolved | partial | ambiguous | not_found` exactly per §8 (`partial` returns the deepest matched ancestor; `ambiguous` enumerates every candidate). Ranges: start/end pair → document-order expansion (§6), reusing `tfref` slot spans.
- [ ] Alignment fallback (§7, `aligned-with` edges): **out of scope** here; resolver returns `partial` where alignment would apply and logs it. Separate issue.

### C. Translation + surfaces

- [ ] `canonical ↔ tfref`: `to_tfref(Reference, adapter)` (resolve, then `tfref.serialize`) and `to_canonical(node, adapter)` (walk up through `code`/`refOrdinal`). Round-trip property test on the fixture and on BHSA when present: `to_canonical(resolve(tfref)) == parse(canonical)`.
- [ ] `/refs` payloads gain `canonical` (null until the corpus carries a scheme); `GET /refs/resolve` accepts a canonical string (detected by `scheme/` prefix vs tfref's `corpus[@v]/`), with `?edition=` to pin `kind: edition`.
- [ ] MCP: `reference_resolve` / `corpus_reference_resolve` accept canonical strings; a new `reference_canonical(ref)` returns the 03 JSON form.
- [ ] `refdisplay.shortcode_payload` adds `canonical`; UI keeps showing tfref (per reference-forms.md) — canonical is for storage/exchange.
- [ ] Docs: `03-references.md` "What is implemented today" note replaced by the real resolver description; `reference-forms.md` consequences updated; CLAUDE.md "Reference identifiers" section.

## Acceptance criteria

- `bible/DEU/4/2/clause-1` and `bhsa@2021/Deut:4:2!clause1` resolve to the same node on a BHSA archive converted with workstream A; `Bible/BHSA/Deuteronomy/4/2` normalises to the former.
- All §8 failure rows have a test (unknown scheme, ambiguous alias, out-of-range → `partial` with chapter node, edition lacks `ling:*` → `partial` with verse, sub-block without edition → `not_found`).
- A monograph converted from EPUB answers `monograph/chapter-4/paragraph-3` with ordinals only; no codes required.
- Corpora converted **before** workstream A keep working: `canonical` is `null`, `/refs` behaviour unchanged, no 5xx.
- `tests/common/test_tfref.py` still pins `common.utils.tfref` == skill script (no change to tfref).

## Non-goals

- Cross-edition alignment (§7) and versification maps.
- Changing the tfref grammar or the compact token.
- A UI for editing alias tables.

## Sequencing and estimate

1. **A** first — it is the only part that touches conversion output and needs a corpus re-release to take effect (bump the manifest `version`; old tfref strings stay valid, their `@version` pins the old build). ~3–4 days incl. validator rule.
2. **B** in parallel on the fixture (`skills/tf-reference-id/assets/fixtures/spanning-mini` + a hand-written `code`/`refOrdinal` variant), ~4–5 days; the registry data is the long pole.
3. **C** last, ~2 days.

## Risks

- **Book-code coverage.** BHSA labels are Latin (`Deuteronomium`); the alias seed must come from `book@en` etc., not hand-typed. Missing aliases surface as `not_found` — make the registry data-driven (YAML under `common/schemas/…/aliases/`) so gaps are a data PR.
- **`refOrdinal` vs `ordinal` drift.** 03 distinguishes canonical numbering from document position; Bible chapters/verses are canonical (skips exist, e.g. verses absent in some editions). Workstream A must take `refOrdinal` from the corpus's own chapter/verse feature values for `bible`, and from position only for `generic:*`.
- **Vercel bundle size.** Alias tables for seven schemes are small (< 200 KB as YAML); keep them out of the function bundle's `excludeFiles` list.

## References

- [reference-forms.md](../reference-forms.md) — decision this issue implements the third leg of
- [03-references.md](../context-fabric/03-references.md) §2–§8, [02-node-taxonomy.md](../context-fabric/02-node-taxonomy.md) §4.8 (`ling:*`)
- `packages/common/src/common/schemas/context_fabric/v1/{reference,edition,content-node,api-payloads}.schema.json`
- `packages/admin/src/admin/ingest/docling_graph.py::_assign_reference_levels`
- `packages/admin/src/admin/converters/_walker.py::SectionSpec` (issue #174)
- `common.utils.tfref` / `refcompact` / `refdisplay`; `skills/tf-reference-id`
