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

# Bible detector follow-up

Restored PR261's scaffold from its pull-request ref because the named remote
feature branch was unavailable. The earlier unpushed `a312a741` object was absent
in this workspace; restored the manual retrieval example and adapter notes here.

The bounded detector is fixture-backed and keeps exact source evidence and
unresolved catalog hypotheses. Verification: Ruff passes; mypy passes across 103
source files; pytest reports 900 passed, 34 skipped (38 linking tests), with the
existing Starlette/httpx deprecation warning. Corpus-document conformance passes
7 tests and 25 fixtures. Both independent and umbrella wheel builds succeed.
Fresh isolated environments import the installed wheels away from the checkout
and run detector/manual retrieval smoke checks under `python -I`. The umbrella
smoke uses `--no-deps` plus Pydantic and verifies the bundled linking surface;
it does not claim full application dependency installation.

No push, merge, deployment, publishing or database changes were performed.

# Offline catalog and resolution follow-up

Added Catalog identification and snapshot-backed Resolver adapters with separate
work-only, verified text, ambiguous edition, unavailable revision and stale/conflict
outcomes. Exact citation context is supplied by callers, not inferred authority.
Detection-to-resolution example preserves reference identity and pending review.

Verification: 910 tests passed, 34 skipped (48 linking tests); Ruff and mypy pass
(105 source files). Existing Starlette/httpx deprecation remains. Graph conformance
passes 7 tests/25 fixtures. Both wheels build. Fresh environments run the resolution
example through each installed wheel under isolated Python away from the checkout.
The umbrella check installs without application dependencies, adding Pydantic for
the linking surface only. No push, merge, deploy, publishing or database changes.
