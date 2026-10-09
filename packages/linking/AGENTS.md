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
coverage for changed invariants and run Ruff, mypy, tests, umbrella wheel builds and
clean install/import checks. Preserve existing graph/scoped-reference contracts.
Do not publish, deploy, migrate production databases, merge or push without
explicit authorization. No credentials are needed for this scaffold.

For integration changes read [production composition](../../specs/reference-linking/production.md).
Keep native asset checks and explicit stream/offset conventions intact. C-USX
bindings require verified advertised targets; editorial acknowledgments are not
delivery receipts. Standalone exports must keep portable instructions and run the
actual core tests against the installed wheel away from the monorepo.

The core source now lives in exegia/corpora-linking. Do not restore a duplicate
workspace package or bundle its namespace in the umbrella wheel. Development
and wheel checks must use the released PyPI dependency.
