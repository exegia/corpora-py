# Owned CTEI archive, version 1

`.ctei` is a ZIP archive containing constrained TEI P5 reading documents and
Corpora metadata. It uses the existing manifest vocabulary; `format: corpus`
and `format_version: '1'` remain unchanged, while `type: tei` distinguishes
the payload. A valid archive does not certify that its source has been
visually collated: the validation response keeps `source_verified: false`.

Submit a conversion through the existing asynchronous API:

```sh
curl -X POST http://localhost:8000/convert \
  -F 'file=@book.epub' \
  -F 'source_format=epub' \
  -F 'output_format=ctei' \
  -F 'name=Book title'
```

`output_format` defaults to `corpus`. Poll `GET /convert/{job_id}`; after
success, `GET /convert/{job_id}/download` serves `application/zip` with a
`.ctei` filename. The job status includes `output_format` and the package
validation summary. `/manifest` and `/versions` read CTEI metadata. The
Text-Fabric graph and mutation endpoints return 409 for CTEI archives.

## Layout

```text
manifest.yml
toc.yml
review.xml
references.xml
history.xml
version_1.0.0/
  d001.xml
  ...
assets/
  mapping.xml
  source/original.<extension>
  conversion/metadata.json
  conversion/evidence.json
  conversion/source-ledger.json
  conversion/receipt.json
  ... source images and other non-TEI resources ...
presentations/
  styles.xml
```

The manifest gets a new UUIDv4, source title, description, language,
language code, inferred category, UTC conversion timestamp, semantic
version `1.0.0`, empty dataset/project IDs and a null thumbnail. Explicit
source descriptions take precedence over generated summaries unless the
request supplies a description. Missing source language uses the requested
`english` / `ENG` default and creates a review item. Script alone does not
establish a language. Common declared language codes map to ISO 639-3;
unknown source language identifiers are preserved.

Every asset, including XML/JSON sidecars, appears once in `manifest.assets`.
Asset paths there are relative to `assets/`, consistent with the corpus
manifest convention. Other package paths are relative to the archive root.
`toc.yml` uses the existing corpus TOC fields and adds explicit reading order
and logical hierarchy. Files split at source-declared parts or chapters;
EPUB spine files and PDF pages do not imply chapters.

`review.xml` is native TEI: `TEI/teiHeader/standOff`, an interpretation
vocabulary and `listAnnotation/annotation/note/p`. Each finding has a stable
ID, a package-local `target` URI and `ana` pointers to its pending status
and category. Empty review files omit the annotation list. Unclear/gap
text, extraction warnings, default language and unverified or unresolved
references remain visible here.

The owned sidecars use namespace `urn:corpora:ctei:1`:

* `references.xml` records each detected source link/cross-reference or
  explicit OSIS citation, its reading-text source URI, target, label and
  resolution status. External links remain unvalidated; no catalog target
  or canonical edition is invented.
* `assets/mapping.xml` records inline graphic targets and supplementary
  resources whose reading placement is unknown. Source resources remain
  available without inventing a location in the reading text.
* `presentations/styles.xml` contains `style` elements with semantic roles
  such as `h1`, `paragraph`, `table`, `note`, `figure`, `caption`, `list` and `poetry`,
  plus target URIs. It contains no CSS, font declarations or layout rules.
* `history.xml` serializes the existing corpus version-row fields: ID,
  label, title, timestamp, current flag, nullable snapshot key, changed
  files, author, approval actor and notes. The initial label remains
  `v1.0`, matching the existing online snapshot convention, while the
  manifest and directory use `1.0.0`. Actors come from the authenticated
  submitter; unauthenticated conversions leave them absent/null.

## Source fidelity and limits

Supported inputs are UTF-8 plain text, EPUB, supported HTML/XML vocabulary,
standalone constrained TEI, and readable PDF text layers. Text, Greek and
other Unicode scalars, inline tails, explicit abbreviation alternatives,
notes and table cells are checked before packaging. The original source,
extracted metadata, extraction findings, source ledger and SHA-256 member
inventory are preserved in assets. Hashes detect changed package members;
they are not a digital signature.

PDF extraction is provisional unstructured prose in one paragraph, with
source images retained and visual-review findings. No paragraph, chapter,
note, table or verse semantics are inferred from pagination. Any unreadable
page blocks conversion; OCR is not automatically accepted. Unsupported TEI
stand-off/canonical schemes, surah structures or semantic linking
attributes are rejected rather than silently discarded. Dataset ZIPs are
not supported as CTEI inputs. Local image resources must be supplied by the
source archive; the converter does not fetch remote images.

Reading documents validate against the bundled TEI P5 4.12.0 schema,
`corpora-tei/0.1.0` RELAX NG and generated Schematron. The bundled ODD and
generation provenance are in `admin/converters/tei/profile/`. ZIP checks
also verify paths, unique member names, bounded sizes, CRCs, UUID identity,
TOC order, exact asset inventory, member hashes, references, review targets,
semantic presentations and typed version history.

## Online persistence

Jobs use the existing result store and owner isolation. HEAD uploads retain
`.ctei`, and initial snapshots use
`conversion-jobs/{job_id}/v1.0.ctei`; later labels remain compatible with
the existing store interface. Local snapshots also retain the extension.
Supabase hydration persists `output_format`, so another instance reports
the correct queued/result filename. Apply the additive `output_format`
column statement in `packages/admin/sql/conversion_jobs.sql` before using
this API version with an existing Supabase job table. No database changes
or remote uploads happen during local tests.

The archive history has a null snapshot key at creation, following the
corpus contract: the snapshot PUT happens after conversion. `/versions`
returns those same typed records; the store resolves a version's key from
the job ID, label and `.ctei` suffix. Database-backed metadata mutations,
restores and TEI editing are outside this initial conversion API.

## Vercel execution

On Vercel, the conversion response attaches an asynchronous FastAPI background task to the existing worker future. The HTTP 202 body is sent first; the ASGI invocation remains active through archive upload and the terminal job-store write. The future is local process state and is neither serialized to Supabase nor exposed in job responses. The configured function duration still bounds execution.

Native TEI lists with an undeclared or unsupported list type retain their entries and are mapped to unordered lists with a pending review finding. Unsupported division types likewise retain the original source attribute in the source asset and produce a mapping review finding.
