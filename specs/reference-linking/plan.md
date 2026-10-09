---
title: Reference linking staged implementation
description: Implemented scaffold and next detector, mapping and lifecycle stages.
tags: [references, plan]
status: in-progress
type: plan
---

# Completed local stages

1. Independent MIT/Pydantic core, stable reference identity, typed selectors,
   conservative retrieval, bounded Bible detection, scholarly recognizer ports,
   unknown discoveries and explicit catalog/passage authority.
2. PDF/EPUB/HTML conversion sidecars and retry-safe persistence; both reader and
   ingest workflows share reference values, review and retrieval.
3. Optional pdfplumber and PyMuPDF glyph-quads, crop/rotation transforms, EPUB native
   CFI ranges and multi-node HTML/browser capture adapters. Unsupported format
   variants reject explicitly; see [capabilities and limits](production.md).
4. SQLite and PostgreSQL working history, exact resource grants, admin entitlement
   synchronization, session/capability checks, discovery management, authenticated
   opt-in HTTP integration, approved snapshot reconciliation, C-USX range/link
   insertion and distinct per-destination delivery receipts.
5. Independent public repository and verified PyPI release of corpora-linking
   0.1.0. Corpora consumes the published package with one namespace owner;
   Homebrew CLI offline commands depend on the released core directly.

[Production composition](production.md) records configuration, API workflows,
format boundaries and extraction commands. The [walkthrough](end-to-end.md) remains
an offline executable example. Implementation is complete for the documented
bounded adapters. Live schema rollout, authoritative production inventory/policy,
provider transport and broader format variants require further operational work.
The core public release is complete; Corpora/CLI release lanes and production
rollout remain separate. No live schema changes or deployment were performed.

# Verification

Run `uv run ruff check .`, `uv run mypy .`, `uv run pytest`, and root `uv build --wheel` against the published core. Build core artifacts
in its independent repository.
Install each actual wheel in an isolated environment and import away from the
checkout. The core needs only Pydantic; a no-deps umbrella smoke installation
must explicitly provide Pydantic for the seam. No network calls should occur
on core import or locator verification.

Results for this scaffold are recorded in [verification](verification.md).
