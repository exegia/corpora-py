---
title: Scholarly citation intake
description: Exact recognizer evidence, catalog hypotheses and separate passage resolution.
tags: [references, citations, scholarly]
---

# Scope

The reusable core now exposes `ScholarlyCitationRecognizer`,
`ScholarlyCitationMention`, `CitationDiscovery` and `identify_scholarly_citation`.
The recognizer protocol accepts a pinned TextSnapshot and returns exact citation spans,
a bibliographic lookup name and an optional typed CitationLocator passage request.
Actual bibliography parsing, author/year grammars, footnote association and model-based
recognition remain provider work. No parser, network service or scholarly authority
is bundled into the core.

Intake verifies Unicode scalar offsets, stream identity, normalization and exact
quote/context before calling the Catalog. An NFC selector cannot silently normalize
a different pinned stream. Catalog results must identify distinct work-only endpoints;
a returned document/passage endpoint is rejected as an invalid identity contract.

# Identity and unresolved evidence

A discovery has its own stable UUID, source selection, original mention, recognizer
provenance and complete work-identification outcome. Every catalog candidate produces
an ordinary unresolved pending-draft Reference hypothesis, retaining the same selected
source and optional passage request. Even one identified work does not assert exact
passage resolution, approval or publication. Multiple candidates remain grouped in the
discovery; callers must not publish one as the chosen work without explicit review.

When identity is unknown or the catalog is unavailable, the discovery remains fully
serializable with no hypotheses. It retains the quote, bibliographic lookup text,
optional passage request and catalog diagnostics. No guessed work UUID or synthetic
work identity is inserted into Reference. This is staged discovery evidence preceding
a Reference whose required work identity can be established. Persist it rather than
discarding mentions that have no Reference yet.

Each intake call allocates new discovery/hypothesis IDs. IDs survive JSON round trips;
they are not derived from title/text/offsets. Retry-aware integrations must retain the
saved record/event identity, not call intake again and deduplicate by citation text.
An explicit re-identification or selection must retain original evidence/history;
this slice does not implement that editing operation or confer trust on recognizer
claims merely because their source offsets are valid.

# Passage retrieval and integration

Known hypotheses use the existing Resolver interface, including SnapshotResolver
with caller-authoritative passage mappings and pinned text. A display page number
or scholarly citation string supplies a request, never exact selection authority.
Ambiguous editions and stale target quotes retain existing resolver outcomes. Whole
work mentions omit the passage locator and still await explicit resolver validation.
Manual references continue using the same Reference/Resolver model.

Run `uv run python packages/linking/examples/scholarly_link.py`. It emits portable
JSON for identified, ambiguous and unknown citations and separately verifies a
synthetic mapped passage. The example performs no database or network I/O.

The umbrella now provides an offline SQLite discovery adapter with registration
events, retained mapping evidence and audited work-selection history. PostgreSQL
discovery persistence now shares the same decision rules; production converter hooks remain staged; they must enforce
resource authorization and retry contracts with working database authority. All
existing graph/reference and C-USX publication contracts remain unchanged.

# Local discovery history

`corpora_py.linking_discoveries.SQLiteDiscoveryStore(working_store, authority_id=...)`
uses the same caller-selected SQLite file as the offline working store. It trusts
caller-supplied actors; it implements no authentication or RLS. Registration requires
a pinned source snapshot and verifies quote/context before saving. Optional complete
original/converted mappings are validated against that snapshot and retained on every
discovery revision.

`register(..., event_id=..., reason=...)` atomically stores version 1 and the registration
event. Its fingerprint covers source text/identity, mention, catalog outcome, provenance
and mappings, excluding newly allocated discovery/hypothesis UUIDs. Identical retries
return the original registration with the original IDs even after later decisions;
changed event evidence conflicts. Distinct events do not deduplicate text. Reusing a
discovery UUID for another registration conflicts.

`refresh_identification` verifies the same pinned source and explicitly reruns catalog
identity, preserving the discovery UUID and existing hypothesis IDs by work identity,
including candidates that disappear and later return. It appends CAS history with
actor/time/reason; it does not choose a work. All original evidence remains in history.
`reject` retains the unresolved discovery; a fresh identification action is required
before selecting a rejected record. Discovery decisions do not confer approval.

`select_work` requires an identified candidate and current version, then atomically
appends the selection decision and creates one ordinary pending/unresolved Reference
with the original hypothesis UUID. All unchosen hypotheses remain in discovery evidence.
Only overlapping native mappings are associated with the working reference; the full
mapping set stays in discovery history. No native citation bounds are projected. The
working store's resolver/review pipeline still verifies and approves the actual link.
Selected discoveries remain immutable intake/decision evidence; further edits use the
working reference's history. Hypothesis ID collisions fail without overwriting links.

Run `uv run python packages/linking/examples/discovery_review.py` for unknown intake,
ambiguous catalog refresh, reviewer work choice and retry ID preservation. It uses
synthetic data and a temporary local database, returning inspectable JSON. This adapter
is append-only through its API; database owners can alter files directly. The PostgreSQL adapter now enforces session/capability/resource checks; production
provider wiring and application routes remain pending.

The optional PostgreSQL adapter is documented in [storage](supabase.md); unlike the
local SQLite actor contract, it checks verified principals and current grants.
