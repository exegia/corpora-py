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

Production conversion-event and working-store adapters currently accept References,
not discovery records; unknown scholarly intake therefore requires a dedicated staged
storage/event adapter before production converter wiring. That adapter must retain
original-file mappings, enforce resource authorization and use event IDs for retries,
with working database authority and no approval on import. This core slice does not
claim that SQLite/Supabase already persist or review unknown discoveries. All existing
graph/reference and C-USX publication contracts remain unchanged.
