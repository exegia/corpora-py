# EPUB to Corpora USX

`POST /convert/epub-to-usx` accepts an EPUB upload and queues the same
EPUB → Text-Fabric → Corpora USX package conversion available to the CLI.
The downloadable artifact is ZIP bytes with the `.cusx` extension.

```bash
curl -sF file=@book.epub -F name='My Book' \
  http://localhost:8000/convert/epub-to-usx
```

The `202` response contains `job_id`, `status_url`, and `ws_url`. Poll
`GET /convert/{job_id}` until `download_ready` is true, then download from
`GET /convert/{job_id}/download`. Authentication, ownership, upload limits,
queue limits, and status handling match the existing conversion API.
`POST /convert` also accepts `source_format=epub` and `output_format=cusx`.
Other source formats cannot request CUSX output. Queued USX jobs use the
job kind `source_format=epub-to-usx`; their result filename ends in `.cusx`.
The existing graph detail routes are for `.corpus`; use the CUSX download
to consume this publication format.

## Python and CLI

```python
from admin.converters import convert_epub_to_usx, validate_cusx

archive = convert_epub_to_usx("book.epub", "book.cusx")
assert validate_cusx(archive)["valid"]
```

```bash
corpora epub-to-usx book.epub -o book.cusx
corpora convert book.epub --to usx -o book.cusx
corpora validate book.cusx
```

The CLI is supplied by `exegia/homebrew-corpora` and requires a build of
corpora-py containing this adapter. Its stdout remains only the result
path; progress, validation and evidence paths go to stderr. Both source
checkouts can be built into wheels for local installation before release.

## Delivered package

The archive contains `metadata.xml`, `license.xml`, `release/styles.xml`,
`release/USX_1/*.usx`, ordered XML JSON equivalents under `release/JSON_1`,
and normalized assets under `release/assets`. The manifest inventories
every delivered resource except metadata.xml itself and uses SHA-256.
Schemas and conformance checks for the unpublished Corpora USX 0.1.0 draft
ship inside the Python distribution, including the pinned USX base.

Content uses semantics, presentation style IDs, and node types. Headings,
paragraphs, emphasis, links, notes, breaks, images and ordinary tables are
represented using USX elements. Explicit chapter numbers remain as supplied;
section identities derive from navigation or content headings. Reading order
comes from the EPUB spine, while boundary schemes describe logical book
sections. XHTML filenames, physical page boundaries, source node IDs and
conversion details are absent from content. An EPUB's file grouping remains
the current packaging granularity; multiple navigation fragments within one
file are linked by canonical anchors, rather than invented chapters.

Bibliographic facts are copied from publication metadata. Prose books use
`versedParagraphs=false` and omit `canonicalContent`. Missing rights are
explicitly unspecified; the converter does not invent permission grants,
license dates, promotions, archive status, scripture profiles or numbering.

## Conversion evidence and validation

`book.conversion-metadata.sqlite` is written beside the archive. The
`conversion_metadata` table stores document identity, source format, source
SHA-256 and an XML evidence blob containing TF mappings, source content
paths, original CSS and conversion diagnostics. This database stays outside
the package. Python callers can select `evidence_path`; the API retains it
beside the server's result file. Intermediate TF data is temporary.

Before publishing the archive, the converter reconciles full spine text
against loaded TF slots and each exported content document before cleaning
publication whitespace. The published XML and JSON collapse whitespace runs
to one space, trim readable flow edges, and remove formatting-only paragraphs.
Spaces between words survive inline markup. Empty or whitespace-only JSON
`content` properties are omitted; empty milestones and anchors retain their
element objects and attributes. Decoders treat missing `content` as an empty
sequence. Source whitespace is retained only in the original artifact/TF
processing evidence, not in publication text.

The converter checks that normalization changed no non-whitespace characters;
external evidence distinguishes exact source-to-TF text from cleaned output
and records raw/published character counts and the whitespace policy. It validates
content grammar and semantics, package metadata/license/styles, resource
inventory and checksums, local links and anchors, and exact XML/JSON ordered
content parity. The finished ZIP is independently unpacked and checked again.
The output file is replaced atomically only after those checks pass.

CSS is scoped to linked stylesheets and normalized into presentation
properties. Unsupported CSS rules and source page constraints are recorded
in external diagnostics. Rendering parity is not certified. Embedded scripts,
MathML, complex inline SVG, encrypted or obfuscated resources, unsupported
media embeddings, and tables with row spans fail explicitly. Conversion is
bounded to 10,000 resources and 512 MiB expanded publication content.
