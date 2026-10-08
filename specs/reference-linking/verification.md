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

# Conversion mapping integration follow-up

Added opt-in umbrella conversion sidecars with converted stream/anchor validation,
all input mappings and overlap evidence for detected citations. PDF/EPUB fixtures
retain native selectors and fidelity without projecting exact native citation bounds.
Missing evidence remains diagnostic; stale mappings and detector anchors reject.
This does not hook existing TF jobs or implement C-USX XML serialization.

Verification: 918 passed, 34 skipped (56 linking tests); Ruff and mypy pass (107
source files); graph conformance passes 7 tests/25 fixtures. Both wheels build.
Fresh environments import installed packages away from the checkout under isolated
Python: independent core resolution smoke and umbrella conversion example with
JSON roundtrip pass. Umbrella smoke provides only Pydantic, not full app dependencies.
The existing Starlette/httpx warning remains. No push, deploy, merge, publication
or live database changes.

# Optional PDF extraction follow-up

Added the optional umbrella `linking-pdf` extra and a pdfplumber extraction adapter.
PDF bytes and UTF-8 stream digests are checked; words retain approximate native
rectangles with explicit spaces/page separators. Actual PDF fixtures test geometry,
citation mapping, blank pages, changed checksums and crop/rotation rejection.
Core dependencies and existing TF conversion jobs remain unchanged.

Verification with the optional extra: 922 passed, 34 skipped (60 linking tests).
Ruff and mypy pass (108 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated installed environments run core resolution and
umbrella PDF extraction against the generated fixture from outside the checkout.
Umbrella smoke supplies Pydantic/pdfplumber dependencies, not the full application
stack. Existing Starlette/httpx deprecation remains. No push, merge, deploy,
publication or database modifications.

# EPUB resource extraction follow-up

Added EbookLib/lxml linear-spine extraction with original archive and converted
stream digest verification, verbatim DOM text/tail policy and approximate resource
mappings. Added a typed epub-resource locator without CFI precision. Fixtures cover
spine order, inline citations, Unicode, empty resources, invalid spine entries,
checksum mismatches and bounded XML extraction. Core dependencies remain unchanged.

Verification: 928 passed, 34 skipped (66 linking tests) with the PDF extra enabled.
Ruff and mypy pass (109 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated environments verify installed core resource
locators/resolution and umbrella extraction/JSON roundtrip against an actual EPUB
fixture away from the checkout. Umbrella smoke supplies only Pydantic/EbookLib/lxml
and their dependencies, not the full application stack. Existing Starlette/httpx
warning remains. No push, deploy, merge, publication or live database modifications.

# HTML extraction and native text retrieval follow-up

Added UTF-8 BeautifulSoup HTML extraction with original-byte/converted-stream digest
checks, text-node correspondence mappings and explicit LF/block rules. HtmlTextLocator
retains parser convention/runtime version, child path and node-scoped scalar quote.
Native retrieval validates asset, parser, path, quote/context without relocation.
Fixtures cover inline citations, entities, Unicode, repeated text, partial manual
selection, stale parser/assets/quotes, invalid paths, fragments and empty content.

Verification: 934 passed, 34 skipped (72 linking tests), with optional PDF support.
Ruff and mypy pass (110 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated installed environments verify core locator JSON
roundtrips/resolution and umbrella HTML extraction, native retrieval and sidecar
roundtrip away from the checkout. Umbrella smoke installs only Pydantic/BeautifulSoup
and their dependencies, not the full app stack. Existing Starlette/httpx warning
remains. No push, deploy, merge, publication or database modifications.

# Offline working-store and review follow-up

Added SQLite working revisions outside the core: compare-and-swap transactions,
actor/UTC-time/reason history, evidence retention, explicit target resolution and
validated review transitions shared by automatic/manual references. Approval stays
separate from publication. Fixtures cover persistence, stale/concurrent writers,
review reopening, evidence, unresolved work exceptions, ambiguity/stale-selection
rejection and audited citation-to-exact-target adoption.

Verification: 949 passed, 34 skipped (87 linking tests), with the optional PDF extra.
Ruff and mypy pass (112 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated installed environments verify core resolution
and the umbrella local review example, preserving IDs and publication draft.
Umbrella smoke provides Pydantic only, not the full app dependency stack. Existing
Starlette/httpx warning remains. No push, merge, deploy, publishing or live database
changes; SQLite files used for verification are local temporary fixtures.

# Approved snapshot and reconciliation follow-up

Added versioned lossless JSON snapshot sidecars, approved audited working exports,
pending-draft imports and stable-ID create/unchanged/conflict planning. Local CAS
checks prevent stale-plan writes; upstream versions never override local history.
Bounded existing USX jmp rendering preserves reference IDs and encoded scopes,
rejecting invented anchors/unresolved targets/invalid XML characters. Full C-USX
insertion and publication/withdrawal acknowledgment remain pending.

Verification: 959 passed, 34 skipped (97 linking tests), with optional PDF support.
Ruff and mypy pass (114 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated installed environments verify core resolution
and the umbrella snapshot roundtrip, preserving IDs and requiring review after
import. Umbrella smoke provides Pydantic only, not the full app dependency stack.
Existing Starlette/httpx warning remains. No push, merge, deploy, external
publication or live database changes; generated snapshots are local fixture data.

# Offline publication acknowledgment and withdrawal follow-up

Added atomic local ledger/working-history updates bound to exact artifact digests,
current audited versions and explicit event IDs. Retries are idempotent; collisions,
stale acknowledgments and unsupported transitions reject. Withdrawal retains artifact
history, next prepared exports omit withdrawn references, and explicit reopening
requires new review. The initial ledger supports one active artifact per review cycle;
it records trusted local assertions and performs no distribution/removal itself.

Verification: 968 passed, 34 skipped (106 linking tests), with optional PDF support.
Ruff and mypy pass (115 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated installed environments verify core resolution
and umbrella acknowledgment/withdrawal/reopening with a temporary local database.
Concurrency and forced event-insert failure fixtures verify atomic CAS and rollback.
Umbrella smoke provides Pydantic only, not the full app dependency stack. Existing
Starlette/httpx warning remains. No push, merge, deploy, external publication or
live database changes; ledger events are local fixture data only.

# Conversion rerun idempotency follow-up

Added atomic local conversion-event registration with caller-supplied authority,
event UUID and detector revision. Identical semantic retries return the originally
allocated IDs/report without modifying current review/publication history. Changed
text/revision/mappings/detector/output conflicts. Distinct events retain distinct
references even for identical passages. Empty runs are durable; concurrent retries,
ID collisions and forced insert failures exercise batch atomicity and rollback.

Verification: 980 passed, 34 skipped (118 linking tests), with optional PDF support.
Ruff and mypy pass (116 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated installed environments verify core resolution
and umbrella event retries preserving IDs and later review decisions. Umbrella smoke
provides Pydantic only, not the full app dependency stack. Existing Starlette/httpx
warning remains. No push, merge, deploy, external publication or live database
changes; event/storage verification uses temporary local fixtures.

# End-to-end local walkthrough follow-up

Added a runnable actual-HTML fixture connecting extraction/mappings, automatic
conversion-event detection and a manual sentence link, shared exact target resolution,
review by separate actors, approved snapshot export/pending imports, retry ID
preservation and withdrawal omission. It writes inspectable JSON/history and local
SQLite artifacts to a selected empty directory; existing content is never overwritten.
Source/catalog/scripture data are synthetic and no remote distribution is claimed.

Verification: 982 passed, 34 skipped (120 linking tests), with optional PDF support.
Ruff and mypy pass (117 source files); graph conformance passes 7 tests/25 fixtures.
Both wheels build. Fresh isolated installed environments verify core resolution
and run the complete umbrella walkthrough away from the checkout with Pydantic/
BeautifulSoup only. Output artifacts are available locally at
`/tmp/reference-linking-end-to-end-demo` and
`/tmp/reference-linking-installed-end-to-end-demo`. Existing Starlette/httpx warning
remains. No push, merge, deploy, external publication or live database modifications.

# Offline Supabase proposal follow-up

Added private-schema SQL and authorization/transaction contracts matching the local
working store, conversion registry and publication ledger. PostgreSQL syntax parsing
with `pglast` succeeds for all 23 statements; `git diff --check` passes. The SQL is
outside migration directories and was not executed. Runtime constraint/RLS tests
and a production adapter remain pending. Public Supabase documentation was consulted;
the changelog endpoint returned HTTP 403. No live project access or modification,
push or deployment occurred. Library code and dependency lockfile are unchanged;
previous wheel and application test results remain applicable.

# PostgreSQL working-store follow-up

Implemented an optional psycopg server adapter for creation/get/history/save,
resolution, review and reopening. It derives actors from the existing JWKS verifier,
rechecks tokens and membership per operation, locks memberships and heads, and
atomically appends revisions with CAS. SQLite and PostgreSQL share lifecycle revision
construction. No schema initialization or HTTP routing is performed by the adapter.
PostgreSQL conversion-event and publication adapters remain future work.

Verification: 989 passed, 34 skipped with both optional linking extras and a disposable
loopback PostgreSQL 17 container. Seven new real-database tests cover independent
capabilities, review/audit, token rejection, tenant isolation, concurrent creation/CAS,
membership revocation and locking, denied client access/history rewrites and rollback
of a failed creation. Authentication results are controlled in database tests; the
existing JWT suite checks cryptographic authentication separately. Ruff passes; mypy
passes for 118 files; graph conformance passes seven tests/25 fixtures. Both wheels
build and isolated imports away from the checkout pass. Core install needs Pydantic
only and has no psycopg dependency. Umbrella smoke supplies psycopg, PyJWT/cryptography
and existing common-utils import dependencies (Pydantic settings, platformdirs,
FastAPI); it is not a full app installation test. The disposable container was removed.
Existing Starlette/httpx warning remains. No live database access, push or deployment.

# PostgreSQL event and publication follow-up

Added authenticated conversion registration, publication acknowledgment/withdrawal,
ledger history/tombstones and repeatable-read export outside the reusable core.
Authority is loaded and locked from the configured space. Event advisory locks
serialize retries; writes use one transaction and preserve prior IDs/versions.
Conversion fingerprint validation is shared with SQLite. Full typed event records
are retained beside queryable envelope fields in the unapplied schema proposal.

Verification: 993 passed, 34 skipped, including 11 real PostgreSQL tests. New coverage
checks concurrent event retries, changed inputs, retained review, independent publish
permission, acknowledgment retries, withdrawal/reopening and rollback after failed
conversion/publication event inserts. Ruff passes; mypy passes for 119 files; graph
conformance passes seven tests/25 fixtures. Both wheels build. Actual-wheel imports
away from the checkout pass in isolated environments; the core has no psycopg
installation. Umbrella import verification supplies existing auth/common dependencies,
not the complete application stack. Existing Starlette/httpx warning remains.
Disposable loopback PostgreSQL fixtures/container were removed. No production schema,
Supabase project, remote delivery, push, merge or deployment was modified.
