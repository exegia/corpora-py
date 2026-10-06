# PDF quality gate and atomic ingestion

**Normative rule:** a PDF whose content cannot be recovered satisfactorily MUST
be rejected as an import. A valid Corpora graph is necessary but insufficient.
Do not accept, persist into the accepted corpus namespace, or publish a recovered
subset of an insufficient document. Diagnostic data may be retained separately
and must remain visibly and mechanically unaccepted.

This draft supplies [decision shape](ingestion-decision.schema.json), a bounded
[decision checker](pdf_acceptance.py), and regression tests. It does not supply
an OCR engine, a universal quality score, or production database enforcement.
Quality assessments must come from actual extraction evaluation/inspection, not
from a schema validator or invented confidence numbers.

## Decisions and measured evidence

| Decision | Meaning and permitted action |
| --- | --- |
| rejected | known insufficient content, parser failure, missing pages during whole-document evaluation, or unresolved material reading-order failure; reject the entire import and keep only optional diagnostics |
| pending-review | no known fatal finding, but source quality, exact candidate binding, or whole-document scope remains unverified; no accepted corpus output or publication |
| accepted | every source page evaluated, content satisfactory or legitimately blank with evidence, material reading order satisfactory, exact source/candidate bound, and graph/mapping checks pass; eligible for one atomic commit |

The source SHA-256 binds the original PDF. `candidateSha256` binds the exact
normalized logical graph using UTF-8 JSON with sorted object keys and compact
separators; array order and string values remain significant. Accepted decisions
cannot be reused on a changed or partial candidate. The experiment additionally
requires one `core:page` node for every source page with asset-scoped, zero-based
decimal page-index source IDs. Deployment may adopt an equivalent explicit page
coverage mapping, but cannot omit the coverage check.

| Evaluation dimension | Current verifiable/proposed criterion |
| --- | --- |
| Coverage | enumerate all original pages; match evaluated indices and mapped page nodes exactly; selected-page samples cannot certify the full PDF |
| Content recovery | zero text from an image-bearing page without successful OCR is a measured failure here; substantial missing/unreadable content is a fatal assessment even if some text was extracted |
| Reading order | compare extracted blocks with source layout where columns, tables, headers or overlaps matter; a known unresolved material failure rejects the document; unverified order blocks acceptance |
| Blankness | preserve a page only as legitimately blank when independently confirmed, for example by rendering/inspection or reliable source-page analysis; empty extraction alone is not confirmation |
| OCR and fidelity | running OCR is not a passing criterion; its recovered content still needs coverage, legibility, ordering and mapping evaluation before reevaluation can accept |

No universal confidence percentage, character-count cutoff, OCR score or allowed
loss threshold has been verified by these samples. Production evaluators must
define source-appropriate checks and evidence for satisfactory recovery. A page
with images or graphics cannot be treated as blank because no selectable text
was found. A partially readable page can still be insufficient when material
content is missing.

## Atomic acceptance boundary

1. Retain source assets and extract into an isolated staging/diagnostic area.
   Failures produce rejected decisions and reports without publishing a partial
   revision.
2. Evaluate the complete PDF and its normalized candidate. Record per-page
   content/reading-order assessments and evidence, source checksum and candidate
   checksum. Detect missing pages and parser failures explicitly.
3. Validate graph/schema invariants and the quality decision independently.
   Recheck source/candidate binding and complete mapped page coverage. A rejected
   or pending decision cannot enter the accepted corpus write path.
4. Commit the complete revision, dependent records, provenance and accepted
   decision in one transaction or atomic manifest promotion. On failure,
   roll back/promote nothing; an existing accepted revision remains unchanged.

This is a logical acceptance policy and storage requirement, not a migration.
Source assets/job diagnostics may persist outside the accepted corpus. The
reference artifact helper emits `unacceptedDiagnostic` with a nested
`diagnosticDocument` for rejected/pending decisions, rather than a bare corpus
document. Its accepted output is an `acceptedImportCandidate`; persistence still
requires the transactional boundary above and a trusted evaluator. Binding a
candidate or filling an assessment field cannot manufacture evidence.

## Real experiment results

The first three sampled pages of `Colwell_rule.pdf` each have an image object and
zero extracted text. No OCR or confirmed blank-page evidence exists. Its import
proposal is **rejected**, with an unaccepted diagnostic graph only.

The first three pages of the prose article produce text, but only three of sixteen
pages were evaluated and source reading fidelity was not visually verified.
Its decision is **pending-review**. It is not an accepted partial corpus.
No real PDF in this experiment was accepted.

Regression checks cover one failed page rejecting the entire document, bounded
scope preventing acceptance, missing pages, material reading-order failure,
OCR without demonstrated quality, confirmed blank pages, parser failure, and
accepted decisions being unable to wrap partial/changed graph candidates.
Whole-document evaluation and production OCR/transactional enforcement remain
future work.
