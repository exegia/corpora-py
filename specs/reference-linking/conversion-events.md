---
title: Conversion event idempotency
description: Explicit rerun identity and atomic registration without passage-text deduplication.
tags: [references, conversion, idempotency]
---

# Event identity and registration

The umbrella ConversionEventRegistry uses the working store's local SQLite file.
A trusted caller supplies a stable authority ID, conversion-event UUID, detector
revision and reason. The event ID identifies one immutable conversion/detection
run; reuse it for retries, not for changed inputs or detector configurations.
The registry does not derive event IDs or reference UUIDs from text or offsets.

`register(conversion, detector, event_id=..., detector_revision=..., reason=...)`
validates the pinned stream/mappings and automatic unresolved pending-draft outputs.
It creates all detected working references at version 1, retains their conversion
evidence, and stores the complete event report atomically in one BEGIN IMMEDIATE
transaction. It records the first successful actor, UTC time and reason. An empty
result is also a durable event, so retries cannot silently turn it into a new run.

# Retry contract

The digest covers the whole converted snapshot, original location mappings,
detector revision and ordered semantic output, including targets, relationship,
provenance and diagnostics. Only newly allocated reference UUIDs are excluded from
the retry digest. The saved report retains those original UUIDs unchanged. Output
order matters; an unstable detector must be fixed or its changed run explicitly
identified, not silently paired by text. Callers must pin detector configuration
and catalog/numbering versions in the declared detector revision and provenance.

On an identical retry, the registry returns the first immutable report and performs
no working-history writes. It does not reset review, overwrite edits, resurrect
withdrawn references or replace resolved targets. Query the working store by the
returned IDs for current state. Another worker may retry the same event; the first
successful actor/reason remain the event's audit identity. Detection runs again
outside the transaction to validate that its semantic result is unchanged.

A changed input, revision, mapping, detector revision or semantic result under the
same event ID raises VersionConflictError. A new intentional event allocates a new
set of references; identical passage text does not merge distinct events or creators.
Changed-run reconciliation across events remains an explicit review operation.
Authorities scope event identities, not reference UUID identity.

# Transaction and integration boundaries

Concurrent identical retries return the same committed event/reference IDs.
An event insert failure or any pre-existing emitted reference ID rolls back the
entire batch. Duplicate emitted IDs and manual/reviewed/published outputs reject
before insertion. The adapter never adopts an existing working reference just
because its endpoint or text matches.

This is an opt-in local orchestration seam; existing conversion jobs are unchanged.
Production jobs must persist/reuse their event identity across retries and establish
trusted actor/authority, archive and configuration policies. The event digest is
content evidence, not an account authorization or raw asset checksum replacement.
It is not a migration or live Supabase operation.

The optional `PostgreSQLConversionEventRegistry` now implements the same fingerprint
and UUID-preserving retry contract using transactional advisory locks and atomic
head/revision/event insertion. Authority comes from the configured space and each
request checks current authenticated contribute capability. See [storage](supabase.md).
