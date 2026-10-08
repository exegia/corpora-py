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
   unavailable and stale outcomes. Conversion integration remains next. Preserve original spelling
   and selection evidence; add no live database or UI dependency.
3. Source adapters: PDF geometry/quads, EPUB native CFI and HTML selection mapping;
   conversion reports declare stream joins, normalization, OCR and fidelity.
   Validate package revisions/checksums and exact endpoint boundaries.
4. Management: versioned working store/history, review transitions and approved
   CUSX export/import with ID preservation, conflict/idempotence tests. Design
   Supabase tables/RLS offline, then require separate authorization for deployment.
5. Extraction: select public naming/version policy, preserve license and fixtures,
   test standalone install, document adapters and establish a separate release
   process. Current root release/publish scripts intentionally remain unchanged.

# Verification

Run `uv run ruff check .`, `uv run mypy .`, `uv run pytest`, independent
`uv build --package corpora-linking --wheel`, and root `uv build --wheel`.
Install each actual wheel in an isolated environment and import away from the
checkout. The core needs only Pydantic; a no-deps umbrella smoke installation
must explicitly provide Pydantic for the seam. No network calls should occur
on core import or locator verification.

Results for this scaffold are recorded in [verification](verification.md).
