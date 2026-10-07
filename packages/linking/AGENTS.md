---
title: Linking agent instructions
description: Boundaries, verification and publication constraints for linking work.
tags: [agents, references]
---

# Agent instructions

Read the root CLAUDE.md and .github/WORKFLOW.md and the
[specification](../../specs/reference-linking/spec.md) before modifying this package.
Keep the core independent of Supabase, UI, XML, TF and heavyweight parsers.
Do not reinterpret identifiers, silently normalize revision text, relocate stale
anchors, choose ambiguous matches, or treat vectors as exact-location evidence.
Validate wire inputs; preserve IDs during serialization. Add focused regression
coverage for changed invariants and run Ruff, mypy, tests, both wheel builds and
clean install/import checks. Preserve existing graph/scoped-reference contracts.
Do not publish, deploy, migrate production databases, merge or push without
explicit authorization. No credentials are needed for this scaffold.
