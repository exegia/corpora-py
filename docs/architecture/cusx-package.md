# Compressed C-USX document package

The current development profile is **corpora-cusx-package/0.2.0**. It is a
multi-document parser projection, separate from the corpus-document v0.4 graph
contract and Text-Fabric .corpus archives. It does not claim upstream USX
scripture conformance or infer canonical book/verse/catalog identities.

## Layout and contract

A .cusx is a ZIP with DEFLATE compression. Every member except manifest.json
has an exact SHA-256 entry in manifest.files.

    manifest.json
    documents/0001.usx
    documents/0002.usx
    trees/0001.json
    trees/0002.json
    snapshots/0001.json
    snapshots/0002.json
    assets/<original EPUB member path>
    references.json
    mappings.json

The [manifest JSON Schema](cusx-package-v0.2.schema.json) is generated from
admin.converters.cusx_schema.PackageManifest; the
[parsed tree schema](cusx-tree-v0.2.schema.json) is generated from the shared
Document/Unit/Token model. The Python validator also enforces relationships
that a JSON Schema cannot express: inventory/hash equality, unique IDs,
reading order, navigation and relocated link targets, JSON/XML correspondence,
and snapshot identity/revision/text equality.

manifest.identity contains shared local work_id, edition_id and package_id.
manifest.documents is an ordered inventory; each entry has id/path, tree,
snapshot, a label and source role, source path/fragment/event range, linear and
in_spine flags, character count and its own complete revision-pinned identity.
Document IDs are package member paths such as documents/0009.usx.
reading_order lists every spine document/segment in source order, including
non-linear items with their explicit flags. supplementary lists non-spine
XHTML documents; no source chapter is silently omitted or guessed.

navigation retains hierarchical TOC entries and source hrefs plus explicit
package document/fragment targets. EPUB3 page-list/landmarks and NCX TOC/page
lists are retained as separate navigation collections. assets inventories the
media, fonts, CSS and other non-XHTML source resources as exact bytes. EPUB
metadata, original HTML envelope attributes, namespace bindings and relocated
head structure are retained in each parsed document's metadata.extra.

## EPUB boundaries and fidelity

EPUB3 TOC is the segmentation authority when supplied; otherwise NCX is used.
Conflicting EPUB3/NCX targets are diagnosed and both navigations are retained.
Spine order determines text reading order. All distinct TOC targets within one
XHTML body establish source element-start boundaries, so several logical
chapters can share a file. Parent TOC groups and nested labels remain in the
manifest rather than being flattened or duplicated into text.

Content before the first target is an explicit preamble document. Shared
enclosing elements are copied as continuation structure across boundaries;
their original source IDs belong to only one segment. Continuation ID evidence
is kept in source_attrs. Every text/tail run belongs to exactly one document.
The writer verifies concatenated segment text equals the original parsed
XHTML body stream before packaging.

Missing/duplicate IDs, missing files, ambiguous package roots/navigation,
repeated spine resources and malformed XHTML fail explicitly. No TOC/NCX
leaves complete, unsplit spine documents with an explicit diagnostic.
Non-spine XHTML, including navigation, is retained as supplementary unless
already present in the spine. External navigation is retained as external
source evidence; it is never fetched.

EPUB structure retains body attributes, element namespace URIs and prefix
bindings, mixed content, SVG, MathML, tables, lists, notes and source IDs.
Text around nested elements is represented by ordered text child Units.
Tokens retain text plus after spacing. Empty-text spacer tokens preserve
leading and whitespace-only runs; children is omitted only when empty.
There is no before field and no automatic citation detector in this path.

The XML uses urn:corpora:usx-extension:0.1 cx:unit elements. Source unit types,
attributes, namespaces and document-scoped IDs are explicit metadata; source
hrefs/srcs are rewritten to package document/asset paths, with original values
in source_attrs. These IDs are not global catalog identities or reviewed
citation anchors. Missing ordinary link targets remain source evidence with
a diagnostic, rather than an invented target.
Embedded CSS URLs, CSS imports and srcset attributes remain verbatim with an
explicit portability diagnostic. Their reader must resolve them against the
source XHTML path; this profile does not parse or rewrite these URL grammars.

No synthetic newlines are inserted between inline units. Snapshot text equals
the actual XML text/tails exactly, including all source whitespace and Unicode
combining marks. Literal carriage returns are encoded as XML character
references to prevent XML line-ending normalization. No NFC/NFKC, accent
stripping, case folding, transliteration or word-boundary inference occurs.
CSS, images and fonts are retained as bytes; this does not promise pixel-identical
browser rendering or OCR of image text.

Non-EPUB sources retain their original bytes under `assets/source/`; the manifest
names this evidence and its SHA-256 source revision. Each document has XML, a
compact JSON tree and an exact revision-pinned snapshot in the same inventory.

- Plain text produces one document. UTF-8 Unicode, CR/LF, indentation, blank
  lines and trailing whitespace remain exact.
- Markdown produces one document with nested sections from explicit headings,
  lists, tables, emphasis, links, images and code. The selection stream is the
  **verbatim Markdown source**, including markup and whitespace; semantic
  descendants carry parsed content as metadata without duplicating stream text.
  The dialect is CommonMark plus tables. Raw HTML is retained as source text.
- Generic XML retains one complete element tree, with source vocabulary,
  namespaces, attributes, IDs, mixed content and parsed text/tails. An actual TEI
  root is recognized even with the `xml` source format. TEI retains its header,
  notes and nested divisions; multiple direct body divisions or TEI corpus
  members establish documents. Structural ancestor wrappers are projected into
  each section while source text appears once. XML entity declarations and
  malformed XML fail explicitly. `xml:base` combined with relative links is
  unsupported and rejected rather than resolved against the wrong directory.
- PDF produces one document per explicit page, with outlines as navigation,
  available metadata, extracted images, native word boxes and pypdf text matrices.
  MuPDF native text order defines the stream; differences from pypdf are reported.
  No glyph, reading-order, layout or visual completeness guarantee is made.
  Encrypted, malformed/repaired, undecodable and blank/unextractable pages fail.
  Raster image placements totaling at least 10% of a page are rejected regardless
  of native text length, including tiled images. This conservative gate also
  rejects some readable illustrated PDFs. Small raster illustrations can be
  retained; text inside them is not transcribed. The auxiliary classifier's OCR
  flags remain review diagnostics when native checks pass. Arbitrary invisible
  text, outlined/vector glyphs and image text cannot be proven complete by these
  checks. No OCR or heavyweight AI pipeline is introduced.

Local linked assets supplied beside the source are retained byte-for-byte;
external URLs are preserved without fetching. An individual HTTP upload cannot
supply sidecar files, so missing resources produce diagnostics. CSS/SVG nested
resource dependencies and multiple TEI target URIs are not recursively resolved.
PDF image bytes are decoded extractor output rather than original PDF compressed
streams; original PDF bytes remain the authoritative source evidence.

## Identity, references and migration

Each snapshot is a corpora_linking.TextSnapshot with stream_id
cusx-itertext/v1, Unicode-scalar half-open offsets, normalization preserve,
document_id and the SHA-256 revision of that exact XML document. The shared
UUID identities are local allocations and need catalog reconciliation before
being treated as shared intellectual identities.

references.json remains empty: conversion invokes no automatic detection,
review or reference publication. mappings.json remains empty with an explicit
native-selection-unavailable diagnostic. Source event ranges/hrefs provide
traceability, not EPUB CFI/geometry/native-selection authority.

load_cusx_inventory(path) in corpora_py.linking_cusx validates the complete
package and returns chapter snapshots/raw XML assets for trusted operator
composition via LinkingInventory.model_validate. It creates no grants or
catalog entries, needs no database for inspection, and does not auto-register
an uploaded book as an authorized provider. Existing exact TextLocator
resolution selects the matching document snapshot; changed document revisions
remain stale/unresolved.

New exports use 0.2.0. Existing 0.1.0 single-document packages remain readable
and validate against their original serializer/separator conventions. Existing
references keep their original package/document/revision; their offsets must
not silently be reused against a new chapter export. Native selection mappings
and catalog reconciliation remain explicit future work.

## API and example app

POST /convert accepts `output_format=corpus` or `output_format=cusx`. The example
exposes exactly these two choices: Corpus (Text-Fabric/Context-Fabric `.corpus`)
and C-USX (`.cusx`). The selected output is captured for each job and its retries;
result filenames, validation counts and manual publication follow that job.
Text-Fabric/TEI dataset ZIPs require the Corpus choice. Markdown also has a
converter on the existing Corpus path. The TF serialization boundary preserves
that pipeline's historical CR/CRLF-to-LF behavior and reports it on affected jobs;
C-USX retains exact line endings. Existing job
polling, WebSocket status, download filenames, retry and manual publication
remain the transport. GET /convert/{job}/manifest exposes the new inventory.
The same package bytes are downloaded and passed to the existing POST /storage
publish action using unchanged Hugging Face repo/bucket settings.

Validation checks the typed manifest, ZIP paths/membership/size, every member
hash, per-document model/XML/snapshot correspondence, unique IDs, navigation,
reading order and relocated link targets. Text-Fabric graph/detail readers
still reject C-USX graph operations explicitly; no C-USX visual reader is
claimed. Nothing is uploaded automatically and conversion changes no live
Supabase schema, credentials or deployment settings.
