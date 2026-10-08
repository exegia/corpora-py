---
title: Reference linking core
description: Isolated linking values and adapter ports for Corpora and future extraction.
tags: [references, python]
---

# Reference linking core

`corpora-linking` (import `corpora_linking`) is an MIT-licensed uv workspace
package with Pydantic as its only runtime dependency. It contains validated
source/target values, typed selection locators, provenance, independent
resolution/review/publication state, conversion mappings, JSON round trips,
conservative text-anchor verification and adapter protocols. It performs no I/O.
Its version is independent of Corpora releases; it is bundled in `corpora-py`
and is not added to the repository's automatic PyPI publishing workflow.

```python
from corpora_linking import Endpoint, Provenance, Reference, TextLocator

source = Endpoint(
    work_id="urn:example:work", edition_id="urn:example:edition",
    package_id="study", revision="1", document_id="chapter",
    locators=(TextLocator(stream_id="body", start=0, end=4, exact="John"),),
)
reference = Reference(
    source=source, target=Endpoint(work_id="urn:example:commentary"),
    provenance=Provenance(origin="manual", agent_id="reader", method="selection"),
)
assert Reference.model_validate_json(reference.model_dump_json()) == reference
```

A work-only target intentionally has no fabricated passage. A `resolved` result
may verify a whole work; it does not automatically imply a passage locator.
Fields are immutable; changes use a new validated instance via
`Reference.model_validate({...reference.model_dump(), "review": "approved"})`.
Pydantic's unchecked `model_copy(update=...)` and `model_construct` are not
validation APIs. Adapter code must validate untrusted records at every boundary.

Build: `uv build --package corpora-linking --wheel --out-dir dist/`.
Tests: `uv run pytest tests/linking`. See the
[implementation specification](../../specs/reference-linking/spec.md) and
[agent instructions](AGENTS.md) for constraints and staged work.

## Bible detection

`BibleCitationDetector` implements `Detector` using caller-supplied `BibleBook`
work IDs and aliases, a stream ID, and explicit profile/scheme/version context.
Call `detect(source, text)` on the complete immutable stream and a fully scoped
source endpoint without locators. It recognizes explicit `John 3:16` and
same-chapter ranges such as `Jn. 3:16–18`, preserving spelling, scalar offsets
and context. It does not infer implicit books, validate verse existence, resolve
editions, or accept compound lists/cross-chapter ranges. Every output is unresolved
and pending review. Colliding aliases emit one hypothesis per catalog work with
ambiguity evidence; consumers must retain all hypotheses together for review.
Reruns allocate new IDs: persistence adapters must implement the documented
reconciliation policy before repeated conversion is integrated.

Run the [manual retrieval example](examples/manual_link.py):
`uv run python packages/linking/examples/manual_link.py`.
It verifies both selections and rejects changed revisions or quote/context mismatches.

## Offline catalog and resolution adapters

`Catalog.identify(name)` identifies works separately from `Resolver.resolve(endpoint)`.
`SnapshotCatalog` matches caller-supplied names exactly and retains collisions.
`SnapshotResolver` uses caller-authoritative `PassageEntry` mappings and immutable
`TextSnapshot` streams. It verifies quote, context, normalization and pinned scope
before returning targets. Work-only resolution proves catalog presence, not passage
coverage. Missing mapped streams report unavailable; stale/conflicting streams
report unresolved; multiple verified editions report ambiguous. Missing candidates
never justify picking the remaining edition.

These offline adapters implement no versification authority or citation parser:
mapping keys include the exact citation spelling, profile, scheme/version and
reading. Alternate spellings need explicit mappings. Snapshot providers must verify
revision/checksum identity before supplying data. These adapters accept one text
locator per passage; native and combined selectors require future adapters.

Run the [detection-to-resolution example](examples/resolve_link.py) with
`uv run python packages/linking/examples/resolve_link.py`. Updating a resolved
reference preserves its ID and pending review; it does not approve or publish it.

## Corpora conversion integration

`corpora_py.linking_conversion` is an opt-in umbrella integration outside this
core. Supply a pinned converted `TextSnapshot`, original-to-converted
`ConversionMapping` records and a detector to `detect_converted_references`.
It validates converted quotes, scope, revision and stream, then returns a JSON
sidecar with unchanged references, all conversion mappings and overlapping native
location evidence. Missing mappings keep the reference with diagnostics.

An enclosing PDF rectangle or EPUB CFI stays block-level evidence. The integration
does not project citation offsets into exact native bounds, upgrade approximate
fidelity, approve records or publish XML. Providers validate original assets,
geometry and CFI and define extraction order/joins. No existing TF conversion job
is automatically changed; C-USX serialization still needs an agreed adapter.
Run `uv run python packages/linking/examples/converted_link.py` for a fixture-backed
EPUB-location example. This example requires the umbrella package.

## Optional PDF extraction

Install `corpora-py[linking-pdf]` (workspace: `uv sync --extra linking-pdf`).
`corpora_py.linking_pdf.extract_pdf_references_input` extracts words with
pdfplumber into the conversion sidecar. Supply fully scoped whole-document
endpoints: original revision is `sha256:` plus the PDF-byte digest; converted
revision is the digest of the emitted stream's UTF-8 bytes. Both are verified.
The adapter's `sha256_revision` helper uses that convention.

The stream joins words with one ASCII space and pages with U+000C, preserving
empty pages and performing no Unicode normalization. Word rectangles use
one-based pages and unrotated top-left points. Word-level geometry is marked
approximate; citation substrings never acquire guessed native bounds. This
initial adapter rejects rotated pages/glyphs, nontrivial CropBoxes and nonzero
page origins. OCR, layout-aware reading order, transforms and quads remain future
work. Tests run with `uv run --extra linking-pdf pytest tests/linking/test_pdf.py`.
The existing TF parser and conversion jobs remain unchanged.
