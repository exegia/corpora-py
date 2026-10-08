---
title: Reference and selection linking scaffold
description: Initial implementation boundaries and proposed cross-format linking architecture.
tags: [references, architecture, cusx]
status: in-progress
type: spec
---

# Purpose and context

Support retrievable links created during PDF/EPUB/HTML conversion into extended
USX/C-USX and by readers selecting arbitrary source content. Scripture citations
are the first planned detector; authors, books and commentaries use extensible
catalog/resolver adapters. A management workflow will resolve, validate, review
and publish automatic and manual links, retaining them in CUSX and Supabase.
Paragraph IDs are optional, never prerequisites for a selection.

This scoped scaffold starts implementation without asserting production
conversion, detection or management support. [Package code](../../packages/linking/src/corpora_linking/models.py)
implements transport-neutral values; [ports](../../packages/linking/src/corpora_linking/interfaces.py)
define future adapters. The [TF seam](../../src/corpora_py/linking.py) validates
existing pinned requests, but does not resolve or convert them into CUSX IDs.

# Contract reconciliation

Preserve the merged PR253/254 design in the
[Corpus Document v0.4 specification](../corpus-document/v0.4.0/specification.md),
[reference forms](../../docs/architecture/reference-forms.md) and
[scoped CUSX links](../../docs/architecture/inter-corpus-refs.md).
The graph transport and USX-extension publication are separate adapters over
one core, not competing mandatory trees. This library does not supersede either
schema or change existing runtime TF APIs. Package/revision/document/optional
anchor fields correspond to the CUSX endpoint proposal; work and edition IDs
retain the graph's bibliographic scope. A graph adapter must translate explicit
identity and revision mappings, never equate package IDs and bundle IDs by spelling.
Core UUID reference IDs must serialize as persistent `urn:uuid:` identifiers in
a future graph adapter. Namespaced unknown graph extensions need explicit,
lossless adapter support before claiming graph conformance; core v0.1 deliberately
rejects unknown fields. No new CUSX XML grammar is established here.

# Requirements and implemented constraints

- One reference has stable opaque UUID identity, source, target, relationship and
  automatic/manual agent/method/evidence provenance. Allocated identity is never
  derived from text, titles, citations or offsets.
- Resolution has `resolved`, `ambiguous`, `unresolved`, `unavailable` outcomes,
  separate from pending/approved/rejected review and draft/published/withdrawn
  publication. Publication requires approval; approval need not falsely resolve
  an unavailable external citation. Resolver implementations must verify targets.
- Exact selections require work, edition, package, immutable revision and document
  identity. Work-only and citation-only targets remain valid requests.
- Text locators use a named stream, nonempty zero-based half-open Unicode scalar
  offsets, exact quote and optional prefix/suffix. Surrogates are rejected.
  `preserve` is default; NFC is opt-in for an explicitly normalized stream.
  Adapters must produce a new revision when normalization changes stored text.
  Browser UTF-16 offsets must be translated before constructing locators.
- PDF selections retain an asset, 1-based page and one or more rectangles in
  unrotated CropBox-relative top-left points. Crop/rotation transforms and page
  bounds are adapter responsibilities. Quads and discontiguous multi-page
  selections are staged, not implicitly approximated by a single rectangle.
- EPUB selections retain asset, resource href and opaque native CFI. CFI syntax,
  resource existence and native offset conversion are adapter responsibilities.
- Structural anchors and citation requests are optional typed locators. A canonical
  citation retains profile, scheme ID/version and optional reading; display text
  is never exact-location authority. The bounded Bible detector recognizes explicit alias chapter:verse ranges;
  catalog validation and exact passage resolution remain external.
- Explicit conversion mappings preserve original and converted endpoints,
  method and exact/approximate/unverified fidelity. Approximate OCR or layout
  mappings never authorize exact target claims.
- Text verification returns stale on revision/quote/context mismatch, and never
  searches for a substitute. Repeated text cannot justify automatic relocation.
  Ambiguity is represented by resolver results with multiple candidates.
  Vector search is optional discovery and never exact-location authority.

# Proposed lifecycle and synchronization (not implemented)

Supabase will be authoritative for working records and append-only lifecycle
history with actor, time, reason and optimistic version checks. A future adapter
uses `ReferenceStore.save` compare-and-swap; it must enforce ownership/RLS and
retain evidence and conversion reports. Approved snapshots export into CUSX with
the same reference IDs and independently pinned source/target endpoints. Export
must not auto-approve or mutate working state. Draft import records are reconciled
by stable ID and content version: identical snapshots are idempotent; conflicting
content requires review; unknown IDs allocate/import explicit namespace identity.
Never deduplicate solely by source/target text, because attribution and relationship
can differ. XML import must not overwrite newer working state or confer approval.
Withdrawn records retain history and trigger explicit publication removal on the
next export. These rules need implementation tests before adapter release.

# Standards consulted and limits

The selector choices are informed by W3C Web Annotation text quote/position
selectors, Readium resource/text locators and EPUB CFI. This package makes no
JSON-LD, Readium or EPUB CFI conformance claim; offset conversions and schema
adapters remain explicit. Source URLs: https://www.w3.org/TR/annotation-model/ ;
https://readium.org/technical/r2-locator-architecture/ ;
https://w3c.github.io/epub-specs/epub33/epubcfi/ .

# Open decisions

Choose catalog/versification authority and first Bible code/alias registry;
confirm CUSX source selection serialization and revision/checksum verification;
define discontinuous and multi-page selection representations and PDF transforms;
then design Supabase tables/history/RLS and XML snapshot conflict rules. None is
a prerequisite for the scaffold. PyMuPDF/pdfplumber/EbookLib are candidate adapters,
not new mandatory dependencies. See [plan](plan.md) for the next slice.

See [adapter investigation](adapters.md) for source-library and CFI constraints.
