---
title: Linking scaffold verification
description: Local checks and wheel installation evidence for the initial scaffold.
tags: [references, verification]
status: verified
---

# Local verification, 2026-10-06

Branch: `feat/reference-linking-library`, based on fetched `dev` commit
`11e2972e5110bf3acbead9819c9171bc960237f8`. Initial checkout was clean.
No remote push, publication, deployment or Supabase mutation was performed.

Executed with Python 3.13.5; uv cache redirected to `/tmp/corpora-uv-cache`
because the default home cache is read-only in this workspace.

| Check | Result |
| --- | --- |
| `uv sync` (with cache override) | Passed; lock changes limited to new workspace package and explicit Pydantic dependency |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/mypy .` | Passed, 101 source files |
| Ruff format check on changed Python files | Passed, six files |
| `.venv/bin/pytest tests/linking -q` | 21 passed |
| `.venv/bin/pytest -q` | 883 passed, 34 skipped; one existing Starlette/httpx deprecation warning |
| `conformance_tests.py` for corpus-document v0.4 | Seven tests passed, 25 indexed fixtures; shape, graph and JSON/XML round trips |
| Independent linking wheel and root umbrella wheel | Both built successfully with `uv build` |
| Independent wheel install in `/tmp/corpora-linking-smoke` | Installed with dependencies; isolated import and reference JSON round trip passed |
| Root wheel install in `/tmp/corpora-umbrella-smoke` | Installed with full declared dependencies; bundled linking core import and pinned TF citation seam passed |
| `git diff --check` | Passed |

Wheel smoke tests used `python -I` from `/tmp`, with imports resolving to each
isolated environment's `site-packages`, not the checkout. Both rebuilt wheels
were reinstalled after the final normalization validation change.

Artifacts (untracked build output):

- `dist/corpora_linking-0.1.0-py3-none-any.whl`, SHA-256
  `36d44d073269206254194cfd4d19a89ede91a134716545a6b12a96027c08bf76`.
- `dist/corpora_py-5.0.0-py3-none-any.whl`, SHA-256
  `6f6a6743df64b8e805246ae7ef516448225c23d30cd4b74d0ad3c0409bb843e7`.

The tests cover Unicode scalars/normalization, invalid offsets/surrogates,
revision and quote/context staleness, repeated quotes, geometry, source scope,
work-only targets, locator/mapping JSON round trips, independent lifecycle
states, ambiguity/cardinality, a fake resolver implementing the public port and
the TF compatibility seam. Live detection, source parsers, Supabase lifecycle
and CUSX serialization are deliberately staged in the [plan](plan.md).
