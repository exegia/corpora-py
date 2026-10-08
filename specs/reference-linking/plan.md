---
title: Reference linking staged implementation
description: Implemented scaffold and next detector, mapping and lifecycle stages.
tags: [references, plan]
status: in-progress
type: plan
---

# Stages

1. Implemented: independently buildable MIT core, public typed values/protocols,
   JSON validation/round trips, conservative scalar-anchor verification, explicit
   conversion mappings, legacy pinned TF seam and Corpora wheel integration.
2. Implemented initial slice: a bounded Bible citation detector with an explicit registry/numbering
   context. Emit unresolved records against fixture text; alias collisions retain all
   hypotheses. Offline catalog and snapshot resolver adapters now cover work-only, ambiguous,
   unavailable and stale outcomes. Opt-in umbrella conversion sidecars now retain location mappings and validate
   converted citation anchors. Atomic conversion-event registration now reuses
   original IDs on retries and rejects changed event inputs. Production converter
   hooks remain pending. Preserve original spelling
   and selection evidence; add no live database or UI dependency.
3. Initial mapping integration and bounded pdfplumber extraction implemented;
   optional PDF extra verifies byte/text digests and emits approximate word geometry.
   EPUB resource extraction now verifies archive/text digests and retains approximate
   spine resource mappings without invented CFIs.
   HTML text-node extraction and pinned native quote retrieval are implemented.
   Remaining source adapters and geometry support: PDF geometry/quads, EPUB native CFI and browser/multi-node HTML selection mapping;
   conversion reports declare stream joins, normalization, OCR and fidelity.
   Validate package revisions/checksums and exact endpoint boundaries.
4. Offline SQLite working store/history and validated review transitions implemented.
   Approved JSON snapshot export/import reconciliation and bounded existing USX jmp
   rendering now preserve IDs with conflict/idempotence tests. Next: agreed
   whole-document C-USX selector embedding remains pending. Local acknowledgment/
   withdrawal events and version-checked reopening are now implemented; remaining
   publication work includes authenticated multi-destination delivery/removal receipts. Offline [Supabase schema and authorization proposal](supabase.md) now defines
   private tables, server authorization and transaction contracts. A bounded PostgreSQL working-store adapter and local runtime permission/CAS tests
   are implemented. PostgreSQL conversion-event registration and publication ledger/export adapters
   now have local atomicity/retry tests. Exact resource grants now protect reads/writes and all retained endpoint evidence.
   Production entitlement/grant provisioning, session revocation, HTTP integration,
   delivery receipts and deployment remain pending and separately scoped.
5. Extraction: select public naming/version policy, preserve license and fixtures,
   test standalone install, document adapters and establish a separate release
   process. Current root release/publish scripts intentionally remain unchanged.

# Integrated walkthrough

The [end-to-end example](end-to-end.md) connects HTML extraction, both creation
workflows, exact resolution/review, snapshot import/export, idempotent conversion
retry and withdrawal into inspectable local artifacts. Production parser hooks,
full C-USX insertion, authoritative catalog/CFI adapters and remote storage/delivery
remain explicitly staged above.

# Verification

Run `uv run ruff check .`, `uv run mypy .`, `uv run pytest`, independent
`uv build --package corpora-linking --wheel`, and root `uv build --wheel`.
Install each actual wheel in an isolated environment and import away from the
checkout. The core needs only Pydantic; a no-deps umbrella smoke installation
must explicitly provide Pydantic for the seam. No network calls should occur
on core import or locator verification.

Results for this scaffold are recorded in [verification](verification.md).
