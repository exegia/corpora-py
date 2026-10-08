---
title: Reference linking application integration
description: Opt-in authenticated HTTP service, native selection adapters and standalone extraction.
tags: [references, integration]
status: implemented
---

# Purpose

Readers and ingest jobs create the same revision-pinned reference values. The working
database is authoritative; exact resolution, editorial approval and publication are
separate decisions. Unknown scholarly works and ambiguous passages remain durable
review evidence. The reusable core has no database, UI, XML or parser dependencies.

# Server composition

`corpora_py.linking_api` is included in the existing FastAPI app. It returns 503
unless explicitly configured. Install `corpora-py[linking-postgres,linking-pymupdf]`
for the production adapters (pdfplumber remains an alternative `linking-pdf` extra).
The schema is an **unapplied proposal outside migrations**. This implementation
has only run against disposable local PostgreSQL. Existing TF routes/jobs retain
their contracts; linking does not reinterpret their IDs or rewrite their output.

Trusted startup calls `configure_linking(app, dsn=..., jwks_url=...,
audience="authenticated", inventory=LinkingInventory(...))`. Alternatively set
`LINKING_ENABLED=true`, `LINKING_DATABASE_URL`, `LINKING_INVENTORY` (a local JSON
manifest path) and `SUPABASE_JWKS_URL`. The manifest contains authoritative catalog,
passage mappings, immutable snapshots, assets and optional Bible detector context.
Asset bytes serialize as base64. Native assets require SHA-256 revisions; C-USX
package revisions may be opaque and require a separate verified `checksum` field.
Each asset/snapshot includes work, edition, package, revision and document identity.
Neither bearer tokens nor arbitrary request bodies become catalog or entitlement
providers. Avoid loading unbounded production libraries into a single manifest;
replace this configured inventory provider with the project's authoritative asset
service while retaining the same scope/checksum validation contract.

Every linking route requires a verified bearer token even when the application's
other routes permit anonymous access. Session, space capability and exact resource
grants are checked on each operation. JWT verification uses the existing JWKS
verifier; auth.sessions deletion or expiry invalidates subsequent operations.
This is not an implementation of every GoTrue session inactivity policy.
Client-supplied creation provenance and lifecycle are replaced with the verified
actor and pending/draft/unresolved state. Edits preserve the original creator;
all revisions record the editing actor. Error responses omit database internals.

The trusted manifest's entitlement records are synchronized through
`python -m corpora_py.linking_bootstrap --space UUID --user UUID
[--expected-version N]`, prompting for an admin token. This consumes configured
server evidence and applies exact resource grants with CAS; it does not create
schemas or infer document ownership. No such command has been run against a live
project. Production owners must supply their real inventory and entitlement policy.

# HTTP workflows

All routes below begin `/linking/{space_id}`. FastAPI's OpenAPI provides typed bodies.

| Route | Operation |
|---|---|
| POST `/references` | Create/edit with explicit expected version and reason |
| GET `/references/{id}` | Authorized revision history |
| POST `/references/{id}/{resolve,approve,reject,reopen}` | CAS lifecycle transition; fresh authorized validation |
| POST `/retrieve` | Exact selected text; stale/ambiguous/unavailable selections reject |
| POST `/browser-selection` | Validate browser capture against pinned HTML tree; return native endpoint |
| POST `/conversion-events` | Read trusted PDF/EPUB/HTML asset, detect Bible citations, register retry-safe sidecar |
| POST `/scholarly-conversion-events` | Run configured recognizer, retain unknowns/hypotheses and native mappings |
| POST `/discoveries`; GET `/discoveries/{id}` | Register exact scholarly span or read discovery history |
| POST `/discoveries/{id}/{identify,reject,select}` | Catalog refresh or reviewer work choice; passage resolution remains separate |
| POST `/export` | Prepare approved JSON snapshot; no publication state change |
| POST `/export-cusx` | Prepare source XML plus matching-ID snapshot; verify advertised target anchors |
| POST `/import-plan`; POST `/import` | Recompute ID reconciliation server-side, explicitly apply one CAS decision |
| POST `/publication/{id}/{acknowledge,withdraw}` | Audited publication intent, distinct from delivery evidence |

A scholarly recognizer is a trusted Python implementation of the public
`ScholarlyCitationRecognizer` port supplied to `configure_linking`, together with
its implementation revision. The service ships no guessed bibliographic recognizer.
Ingest jobs assign durable event IDs to ordered mentions before registration. Each
mention commits independently, allowing partial-job retry with original IDs; changed
inputs reject. A shortened subsequent recognition list never deletes earlier records.

# Exact native adapters

PyMuPDF extraction uses rawdict glyph order, LF between lines, U+000C between
pages and no normalization. Native selectors use `pymupdf-body` scalar ranges plus
clockwise convex glyph quads in unrotated CropBox-relative top-left points (72 points
per inch), with one-based pages. `pdf_display_quad_to_native` transforms rotated
viewer coordinates in those same point units; pixel zoom must be translated by the
viewer first. Crop and rotation fixtures pass. Quad/text correspondence is verified
against the pinned bytes; enclosing rectangles remain approximate evidence.
Multi-page selections use ordered per-page fragments; retrieval joins them with
U+000C. This does not promise OCR, logical reading order, CSS layout or visual
semantics. PyMuPDF has AGPL/commercial licensing; it remains an optional umbrella
dependency and is excluded from the MIT reusable core.

EPUB CFI resolution verifies container, package spine, resource href, element paths,
optional simple ID assertions and native UTF-16 character offsets against the pinned
archive. `make_epub_cfi_selection` builds ranges from the actual resource DOM;
`retrieve_epub_cfi_selection` validates exact quote/context in `epub-cfi-dom`.
That native DOM stream includes head text and differs from the EbookLib converted
body stream. Existing conversion mappings remain explicit resource correspondence;
no flattened body position becomes an invented CFI. Supported CFIs are same-resource
character ranges; text assertions/escaping, side bias, temporal/spatial locations,
multiple indirection, point-only selections and cross-resource ranges reject.
DOCTYPE-containing XHTML is deliberately unsupported. Unsupported locators remain
serializable in the core and unresolved by this bounded adapter.

HTML multi-node selectors contain start/end parser child paths, scalar node offsets
and an exact `html-body` selection. Browser UTF-16 offsets translate explicitly;
a surrogate-pair interior rejects. `examples/browser/browser_selection.js` captures
all eligible browser text nodes and a selection. The server accepts paths only when
the complete captured tree matches its pinned BeautifulSoup parser tree. Browser
repair, live DOM mutation or changed parser versions reject; no quote search is used.
The adapter is not a browser rendering engine and does not evaluate CSS visibility.

# C-USX and graph reconciliation

`linking_cusx` uses the existing `urn:corpora:usx-extension:0.1` namespace, paired
`cx:boundary` passage ranges with explicit advertised `cx:id`, and standard USX
`char style="jmp"` links with `urn:uuid:` link IDs. Its stream `cusx-itertext/v1`
is XML text/tails in order, with no separators or normalization. It accepts exact
selectors over a supplied pinned converted snapshot, not arbitrary native offsets.
Paragraph IDs and sentence numbering are unnecessary. Cross-node links use several
jmp fragments with one stable reference ID, preserving text and inline structure.
Overlapping links need editorial reconciliation and reject. Native retrieval also
verifies uniquely advertised structural anchors or paired cross-node ranges. Text targets require
explicit published anchor bindings; HTTP export verifies paired boundary positions
or unique structural anchor advertisement in trusted target assets. The original
selectors and mappings remain lossless in working history and the JSON sidecar.
Prepared XML is a new artifact: its byte checksum must enter publication inventory;
package revisions remain assigned by that inventory, never silently rewritten.

The Corpus Document v0.4 graph contract is preserved and its existing conformance
suite passes. This USX adapter does not claim graph wire conformance, equate graph
bundle IDs with package IDs, or replace existing TF APIs. A future graph serializer
must supply explicit identity/revision mappings and preserve graph extensions.

# Delivery and extraction

`PostgreSQLDeliveryReceipts` accepts trusted provider evidence separately from
editorial acknowledgment, keyed by publication event, artifact, destination and
opaque provider receipt. Admin capability and retained resource access are required;
retries preserve IDs, mismatched artifacts/statuses reject, and removal receipts
refer to withdrawal events. Several destinations can have independent receipts.
The adapter sends nothing and provides no client endpoint for asserting delivery.
Actual transport and verification of a real provider's signed receipts belong to
that configured provider. No remote publication/removal has been performed.

Run `uv run python bin/build/export_linking.py /tmp/new-linking-source` with a
nonexistent destination. It exports the independent project, MIT license, portable
agent instructions, three core examples and the actual core detector/resolver/
scholarly tests, adjusting only their example paths. Build both wheel and sdist
from that tree and run tests against an installed wheel away from the checkout.
Version 0.1.0 and package naming remain provisional until a separately authorized
public release; the exporter adds no release automation and does not publish.
