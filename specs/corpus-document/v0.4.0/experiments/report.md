# Real-source document ingestion experiments

Date: 2026-10-04. Target: unpublished Corpora Corpus Document **0.4.0**.
Six Library samples and two explicitly supplied Downloads USX archives were
read. No public GitHub sample was needed. Originals were not modified: source SHA-256 and modification
times were checked again after every projection. Text-Fabric caches were built
only in a temporary copy, never in the Library dataset.

This report contains source selections, checksums and structural measurements,
not private document text. The machine-readable [results](real-source-results.json)
pin exact source bytes, parser packages, baseline implementation files and
projection checksums. Generated projections containing private text remain in
ignored `dist/private-corpus-experiments*/` and are excluded from specification
bundles. Authorization to read a Library item is not redistribution permission.

## Extraction and mapping are separate stages

The bounded runner implements this experimental path:

```text
source bytes + checksum
  → source-specific extraction/recognition policy
  → extracted text, spans, source order, explicit/inferred evidence, quality losses
  → format-independent Corpora mapper
  → schema + cross-record graph checks + target JSON/XML round trips
```

`Extraction` is an experiment-local evidence envelope, not a new application
contract. Extractors use source tools to identify text and boundaries. The mapper
accepts that evidence and allocates Corpora records without depending on PDF,
EPUB, TEI or Text-Fabric objects. Every projected node distinguishes explicit
source evidence from a heuristic/hypothesis. Schemes and aliases do not determine
identity. `language=und` is used rather than guessing language from content.
Only the declared selected scope becomes an immutable edition revision.

The existing plain-text parser is exercised directly as a comparison baseline.
PDF extraction uses the same `pypdf.extract_text()` boundary as the existing PDF
parser. EPUB mapping follows the OPF reading spine explicitly, rather than
assuming manifest enumeration is reading order. No runtime parser was changed.
The [PDF quality gate](../pdf-ingestion-policy.md) runs after mapping and binds
the source and exact candidate. Rejected/pending PDF outputs are wrapped as
`unacceptedDiagnostic`, not emitted as accepted corpus documents. Graph
conformance and import acceptance are separate results. All other projections
remain experimental; no application import was adopted.

## Selected samples and observed coverage

| Sample | Exact selection | Observed projection | Source structure and uncertainty |
| --- | --- | --- | --- |
| Short plain-text document | Library `of4.txt`, complete UTF-8 file | 11,554 scalars; 22 nodes including 21 inferred paragraphs | exact bytes round-trip; blank-line boundaries are inferred, not authored semantic paragraphs |
| Paginated prose article on throne-vision tradition | `The_Tradition_of_the_Throne_Vision_in_th.pdf`, pages 0–2 of 16 | 8,231 scalars; three page nodes; eight total nodes | **pending-review**, unaccepted diagnostic only; bounded scope and reading fidelity unverified; cross-page window is a hypothesis |
| Image-based PDF negative case | `Colwell_rule.pdf`, pages 0–2 of 66 | all three pages extract zero scalars; each has an image object; three positioned page nodes | **rejected** as an import; no OCR or confirmed blankness; two separators are not recovered document content |
| Phaedrus EPUB | `pg1636-images.epub`, first three nonempty linear XHTML spine documents of six | 208,520 scalars; 412 nodes; 396 explicit paragraph elements; three links retained | OPF spine order differs from manifest order; source text/tails preserved under XML decoding; layout/media and full link resolution not verified |
| TEI-like manuscript transcription | `FINAL_TRANSCRIPTION_version104.xml`, `ab[@id='V-B1K22V1-01-GEN']` | 138 scalars; 51 nodes; 24 selected words; 15 positions; one rejected reading stored separately | unnamespaced TEI root; first `rdg` selected by an explicit experiment rule, not scholarly preference; outer page context detected but not reconstructed |
| Peshitta Text-Fabric data | `ETCBC-pheshitta-tf`, verse node 428562, slots 1–7 | 34 scalars; nine nodes; exact `{word}{trailer}` concatenation; edition-scoped citation resolution | 32,710 book/chapter/verse coverages checked, none discontinuous; synthetic discontinuity tests remain necessary |
| Supplied USX archive A | `text-3aefb10641485092-252238.zip`, `release/USX_1/LUK.usx`, chapter 1 | USX 3.0; 7,495 reading scalars; 139 nodes; 80 paired verses; 39 poetry lines; two footnotes | 20 verses cross layout blocks; inserted separators disclosed; one chapter of one of 27 USX members |
| Supplied USX archive B | `text-47f396bad37936f0-269494.zip`, `release/USX_1/LUK.usx`, chapter 1 | USX 3.0; 7,503 reading scalars; 137 nodes; 80 paired verses; 41 footnotes | ten explicit paragraph blocks; no poetry or cross-layout verse spans in this selection |

Checksums and byte counts for the original files and all twelve TF feature files
are recorded in `real-source-results.json`. The report also records exact EPUB
member names, selected PDF page indices, source TF section metadata and parser
versions. Source format versions are stated only when evidence exists: TEI
schema hints do not prove TEI conformance, filenames are not schema versions,
and the TF loader version is distinct from the source dataset's metadata.
The two ZIP checksums and exact member paths/checksums are also pinned. Unsafe
member paths, symlinks and duplicate member names are rejected; selected source
XML is parsed without DTD/entities or network access. Private archive members
are never copied into the public-oriented bundle.

## Material findings

1. **Whitespace must survive the mapping boundary.** The existing plain parser's
   reconstructed output is 169 scalars shorter on the real sample. Its token
   path drops leading/interparagraph whitespace. The new experimental path keeps
   the original decoded stream once and uses inferred paragraph anchors; it
   matches the UTF-8 bytes exactly. This finding does not automatically authorize
   or implement a runtime parser fix.
2. **Reading order is source-specific evidence.** The selected EPUB's manifest
   order differs from its OPF spine. The experiment follows the spine, stores
   original member/element identifiers and preserves nested text/tails once.
   Three source links are retained as attributes, with no assertion that their
   destinations were resolved. URI fetching was not performed.
3. **PDF extraction fidelity needs its own result.** The prose pages yield text,
   but original layout reading order is not proven. Blank-line blocks are
   `experiment:paragraphCandidate`, not asserted authored paragraphs. A boundary
   window crosses two page anchors to test representability; it carries an
   explicit hypothesis label. The image-based import is **rejected**, although its
   internal diagnostic graph conforms. The prose sample remains **pending-review**.
   Neither produces an accepted partial corpus. No real PDF was accepted. Known
   material loss or reading-order failure rejects the whole document; running OCR
   alone cannot pass. Legitimimately blank pages require independent evidence.
4. **Point positions belong to the independent core.** Empty PDF pages and TEI
   line markers need zero-width locations. Draft 0.4.0 generalizes the earlier
   source-specific position projection into `node.position` with capability
   `core:positions`. Position and text anchor are mutually exclusive. Streams
   and scalar bounds are verified; empty streams allow offset zero. No fake
   character or zero-length text segment is introduced.
5. **Alternative readings cannot be concatenated indiscriminately.** The TEI
   experiment selects one apparatus reading, keeps the other in an annotation,
   retains supplied/highlight text and source attributes, and excludes note
   bodies from base reading text. Whitespace inside rejected apparatus branches
   is not part of the selected reading. This is a declared projection policy,
   not full manuscript reconstruction or a general TEI adapter.

## References, notes and provenance

Real USX start/end IDs are paired in the selected chapter, with explicit
paragraph/poetry structures overlapping verse spans. Footnote insertion points,
body marks and original note/character attributes survive target JSON/XML round
trips. Both sources declare USX 3.0; official 3.1.1 guidance is not a substitute
for validating their actual source version. The entire archives' structural
metadata contains no `ref`, cross-reference note (`x`), `ms`, table, sidebar or
peripheral elements. Those cases remain synthetic coverage. Textual reference
strings inside notes were not interpreted as resolved targets. Upstream USX
schema validation and complete style semantics were not run.

Experiment IDs and work/edition placeholders support reproducible graph checks;
production catalog reconciliation is not inferred from filenames or book codes.

PDF page addresses and the selected TF verse have versioned, edition/revision
scoped schemes. Their ordered target mappings validate; missing keys return
unresolved and unavailable scheme versions return unavailable. The synthetic
conformance suite retains ambiguous cases and cross-reference notes. EPUB hrefs
and TEI source attributes remain opaque evidence, not fabricated citation edges.
This experiment does not establish a general cross-reference parser.

TEI line/note positions and empty PDF pages use the same core position field as
the USX synthetic note fixtures. Annotation authorship is not inferred from
software attribution: the experiment agent states who performed the projection.
Asset hashes identify complete source bytes even when the selected content is
partial. Import reports disclose inserted separators, excluded/alternative
content, unavailable OCR, omitted features and unverified layout semantics.

## Bidirectional structured-format adapters remain a design requirement

| Structured format | Import boundary | Export boundary and present status |
| --- | --- | --- |
| Corpora JSON / Corpora typed XML | validate shape, graph and required capabilities | logical values and unknown optional extensions round-trip in the tested codec; database and network round trips remain unimplemented |
| Text-Fabric | map ordered slots, explicit text/trailer policy, node coverage and features | export a declared slot policy and supported feature/edge subset; never claim recovery of original slots from arbitrary anchors; production import/export not implemented |
| TEI/XML | choose reading policy; map source text/tails, milestones, apparatus and IDs | declare supported TEI vocabulary/profile and standoff policy; preserve unsupported source data/assets where possible; no source-byte or general XML reconstruction claim |
| USX | choose exact source version and scripture/peripheral projection; reconcile numbering separately | select a compatible edition, reference scheme and supported marker profile; arbitrary overlapping Corpora structures may require a lossy view or explicit rejection; no production exporter implemented |

Ordinary PDF/EPUB/plain-document ingestion is the primary demonstrated path.
Structured formats are additional import/export representations. Exporters must
report omitted or transformed semantics and fail unsupported required
capabilities, rather than silently claiming a universal reversible conversion.

## Reproduction and validation

Run these from the checkout or portable bundle, substituting the authorized
Library directory. Private output must remain outside `specs/` and Library.

```sh
uv run --no-project --with-requirements specs/corpus-document/v0.4.0/experiments/requirements.txt python scripts/run_corpus_document_experiments.py --library "/path/to/Library" --out /tmp/private-corpora-projections
uv run --no-project --with-requirements specs/corpus-document/v0.4.0/experiments/requirements.txt python specs/corpus-document/v0.4.0/experiments/test_extraction_mapping.py
uv run --no-project --with jsonschema python specs/corpus-document/v0.4.0/conformance_tests.py
```

To reproduce the real-USX experiments, repeat `--usx-zip` for the two supplied
Downloads ZIP paths. Source hashes must match the pinned report. Members are
read in memory; original archives stay unchanged.

The runner rejects source checksum or baseline implementation mismatches, verifies
reproduced projection hashes, and checks source bytes/modification times again.
Direct parser package versions are pinned; transitive dependencies and platform
font/layout behavior are not a fully hermetic environment. It never downloads
missing source documents. Library items must be locally readable.

Eight real-source diagnostic/experimental projections pass schema/graph checks
and target JSON/XML round trips. PDF decisions are separately rejected/pending.
Thirteen regression tests exercise extraction boundaries, atomic PDF rejection,
blank-page evidence, OCR limits, scope/candidate binding, safe ZIP handling and
USX milestone/note mapping.
The synthetic suite exercises graph negatives and source concepts absent from
these samples. Successful graph validation proves contract consistency, not
correct OCR, source semantics, or visual reading fidelity.

Remaining work is production adapter design, whole-PDF visual/OCR quality
evaluation and atomic persistence enforcement, real discontinuous linguistic
examples, source-level XML/USX validation,
and consumer bindings/distribution. The six-project distribution remains
outstanding. No runtime application or other project was migrated.
