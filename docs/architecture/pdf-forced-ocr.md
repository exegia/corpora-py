# Forced PDF OCR and source reliability

Both PDF → C-USX and PDF → Corpus use the same process-isolated Docling worker.
Every page uses full-page Tesseract OCR, including PDFs with an existing text layer.
The selected profile is `corpora-docling-forced-pdf-ocr/2`: Docling 2.137.0,
Docling Core 2.101.1, IBM Models 4.0.3, Parse 7.22.2 and tesserocr 2.11.0.
`packages/admin/src/admin/parsers/pdf_ocr.lock.json` pins package versions, model
repository commits and model/language file SHA-256 values. Heron provides layout,
TableFormer accurate provides table structure, and tessdata_best provides English,
Hebrew and Ancient Greek OCR. The provenance records the actual Tesseract build.

## Prepare the worker

Use the repository lockfile and Docling extra, or an isolated Python 3.12 environment:

```sh
python3.12 -m venv /absolute/path/ocr-runtime
/absolute/path/ocr-runtime/bin/pip install docling==2.137.0 docling-core==2.101.1 docling-ibm-models==4.0.3 docling-parse==7.22.2 tesserocr==2.11.0
export CORPORA_PDF_OCR_PYTHON=/absolute/path/ocr-runtime/bin/python
export CORPORA_PDF_OCR_MODELS=/absolute/path/ocr-models
export CORPORA_PDF_OCR_LANGUAGES=eng,heb,grc
export CORPORA_PDF_OCR_DEVICE=auto
WORKER=packages/admin/src/admin/parsers/pdf_ocr_worker.py
"$CORPORA_PDF_OCR_PYTHON" "$WORKER" --models "$CORPORA_PDF_OCR_MODELS" --prepare
"$CORPORA_PDF_OCR_PYTHON" "$WORKER" --models "$CORPORA_PDF_OCR_MODELS" --check
```

Preparation downloads public model assets at locked revisions and verifies their
hashes. Conversion is offline; it does not upload the source PDF. The API checks
versions and assets before accepting a PDF job. A missing or changed asset is an
error. Worker device options are auto, cpu, mps and cuda. There is no native-text
fallback and no acceptance of a partial Docling result.

## Snapshot and provenance

C-USX retains `assets/source/<original-filename>.pdf`, `assets/pdf/ocr/snapshot.json` and
`assets/pdf/ocr/provenance.json`. Corpus retains equivalent files in
`corpora/pdf-ocr/`, including `source.pdf`. The snapshot includes the complete
Docling document and the projected page blocks. Provenance records the original
PDF hash, canonical JSON snapshot hash, lock hash, package/model versions, OCR
languages and pipeline settings. Page blocks retain their Docling geometry.
Hashes establish identity and integrity; they do not establish source fidelity.

## Portable C-USX review evidence

The application bundles the completed assessment into PDF C-USX exports before
making them downloadable. Automatic comparisons include:

- `assets/pdf/review/reliability.json`: the full score, decision, thresholds,
  method, normalization, dimension scores, every mismatch with page/character
  ranges, and source/conversion/comparison hashes.
- `assets/pdf/review/independent-ocr.json`: the independent worker's complete
  snapshot and its canonical snapshot SHA-256, including every page's text,
  structured blocks, raw model responses, rendered pixel hashes and model metadata.
- `assets/pdf/review/independent-ocr.lock.json`: the exact pinned comparison
  runtime/model/binary lock referenced by that snapshot.

These optional assets use the existing C-USX 0.2.0 manifest asset/file inventory;
each file is listed and SHA-256 indexed. The report's `bundle` links the evidence
paths and binds the assessment to every exported USX document revision. Original
PDF, source snapshots, document identities and existing member bytes remain
unchanged. The writer validates all evidence and atomically replaces the archive.
A mismatched source, changed document revision, missing page or incorrect
snapshot/lock hash prevents successful packaging.

`validate_package` on a copied archive checks those bindings and returns its
embedded `source_reliability` report with `checks.pdf_review_evidence`, without
requiring the server, local cache or OCR runtime. This verifies evidence integrity,
not source accuracy. Manually reviewed reference providers bundle the report;
they do not claim an independent model snapshot when none was generated.

## Independent comparison

The example app uses an independent Surya OCR 2 worker to read rendered original
PDF pixels. It never receives Docling output or the PDF hidden text layer. Every
page must finish before a score is assigned. Install the comparison runtime in a
separate environment, preserving the Docling environment:

```sh
python3.12 -m venv /absolute/path/comparison-runtime
/absolute/path/comparison-runtime/bin/pip install surya-ocr==0.22.1 pypdfium2==5.14.0 Pillow==10.4.0 beautifulsoup4==4.15.0
export CORPORA_PDF_COMPARISON_PYTHON=/absolute/path/comparison-runtime/bin/python
export CORPORA_PDF_COMPARISON_MODELS=/absolute/path/surya-ocr-2-gguf
export CORPORA_PDF_COMPARISON_BINARY=/absolute/path/llama-b11534/llama-server
```

`pdf_comparison.lock.json` pins the GGUF model revision, file hashes and exact
llama.cpp binary hash. Provision those files before starting the API; the worker
verifies them and package versions and runs offline. Rendering uses 192 DPI.
Incomplete, failed or token-limited recognition cannot produce a passing score.
Atomic per-page checkpoints retain text, blocks, model responses and rendered
pixel hashes under `corpora/pdf-comparison` in the platform user cache (override
with `CORPORA_PDF_COMPARISON_CACHE`). Source, worker code, lock and runtime paths
bind each cache key. Retry resumes valid checkpoints; changing the worker or lock
starts a separate snapshot. Reports expose both conversion and comparison hashes.

The score is an **automatic OCR agreement estimate**. Both engines can make the
same mistake. It does not certify layout, table relationships, notes or selection
anchors. Manual review remains necessary for those requirements. Automatic
comparison normalizes canonical Unicode equivalents and whitespace runs while
preserving word boundaries, word order and Hebrew/Greek marks.

A manually reviewed reference may take precedence through
`CORPORA_PDF_REFERENCE_DIR`.
The filename is the original PDF SHA-256 hex digest followed by `.json`:

```json
{
  "source_sha256": "sha256:<original-pdf-digest>",
  "verified_against": "visible-pdf-pages",
  "reviewed_snapshot_sha256": "sha256:<ocr-snapshot-digest>",
  "structure_reviewed": true,
  "pages": {"1": "Verified source transcript", "2": "Next page transcript"}
}
```

References must cover every page and be verified against the visible PDF, with
layout, tables, notes and image treatment reviewed for the exact OCR snapshot.
Do not generate the reference from the PDF hidden text layer or converted text.
A trusted independent visual review provider can replace this callback through
`run_conversion(pdf_comparison_provider=...)`. Without either a configured
automatic worker or a complete reviewed reference, acceptance remains unscored.

The validator reads text from the final C-USX snapshots or archived Text-Fabric
page slots. It compares Unicode NFD streams, preserving whitespace, order and
combining marks. Each agreement score is `100 × 2 × matched characters /
(reference characters + converted characters)`, using SequenceMatcher without
autojunk. The final score is the lowest whole-text, Hebrew and Greek agreement
score for scripts present in the reference. A script appearing only in converted
text is still a text mismatch; it does not create an empty-reference script
dimension that forces an English document to zero. This is a declared agreement metric,
not a probability of correctness or Docling confidence. Mismatches contain page
numbers, expected/actual text and offsets into the NFD streams.

| Score | Result |
| --- | --- |
| Below 50% | Loss; acceptance held; suggest another format such as EPUB/HTML |
| 50% through 90% inclusive | Pass with review and manual edit required |
| Above 90% | Pass |
| Missing/incomplete comparison | Unscored; acceptance held |

Policy uses unrounded scores. Review passes remain downloadable; loss and
unscored jobs fail acceptance and download returns 409. Job validation and
`POST /validate` by job ID retain the score and mismatches; the conversion UI
shows the verdict and paginates all mismatches. A path-only integrity check has no
independent source comparison. No manual editing interface is added here.

For a first reference review, create a draft directly with the worker:

```sh
"$CORPORA_PDF_OCR_PYTHON" "$WORKER" --models "$CORPORA_PDF_OCR_MODELS" --source /absolute/path/book.pdf --output /absolute/path/draft.json
```

Review this draft against the visible pages, record the verified reference and
snapshot hash, then submit the PDF conversion. Changing the snapshot invalidates
its previous structure review. Original PDFs remain read-only.

## Large PDF progress and retries

The worker emits confirmed page-assembly counts through a private hook verified
against pinned Docling 2.137.0. Progress is streamed to the job log and UI. PDF
watchdogs measure 15 minutes without worker/page/stage progress, rather than
15 minutes of total runtime; a stalled OCR subprocess is terminated. Jobs waiting
for the serialized OCR worker remain waiting. Polling has the same idle policy.
Timestamped progress persists through the existing job log column, without a
database migration. Non-PDF server timeouts retain their existing behavior.

The version-2 profile constrains paragraph merge prediction to contiguous page
groups. This retains page boundaries and avoids merged-text character spans
that can be inconsistent after Docling removes a continuation hyphen. The full
Docling document and page provenance remain in the snapshot.

Completed OCR snapshots are cached under the platform user cache at
`corpora/pdf-ocr-results` (override with `CORPORA_PDF_OCR_CACHE`). Cache keys bind
the PDF hash, worker code hash, lock hash, languages, device and worker Python
path. A retry checks the locked runtime and source/snapshot hashes before reuse,
and reruns archive/source validation. Cache entries use private file permissions.
Changing the code, lock or options generates a new cache key. No cached result
bypasses the reliability score or acceptance policy.
