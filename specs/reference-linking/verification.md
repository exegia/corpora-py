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

# Exact resource authorization follow-up

PostgreSQL adapters now require explicit per-user exact endpoint-scope grants in
addition to space capabilities. They check retained history, resolver candidates,
original/converted mappings and event reports before returning data or committing
writes; event replays and exports recheck grants. Grant rows remain locked until
commit so ordinary revocation serializes with authorized operations. No wildcard
work grants, implicit admin bypass or production entitlement provisioning is added.

Verification: 999 passed, 34 skipped, including 17 real PostgreSQL tests. Six new tests
cover grant revocation across reads/writes/review/events/export, work grants failing
to authorize private document versions, denied resolver candidates, separately
protected original mappings, rollback on denied conversion and grant locking versus
revocation. Ruff passes; mypy passes for 120 files; graph conformance passes seven
tests/25 fixtures. Both wheels build and actual-wheel isolated imports away from
the checkout pass; the core remains independent of psycopg. The umbrella smoke
checks exact resource scope distinctions with existing auth import dependencies;
it does not install the full application stack. Existing Starlette/httpx warning
remains. Disposable local PostgreSQL was removed. No live Supabase project, deployment,
push, merge or production migration was touched. Production entitlement synchronization,
JWT session revocation and HTTP integration remain staged.

# Entitlement synchronization and session validation follow-up

Added an authenticated admin-only trusted entitlement snapshot synchronizer with
provider binding, local CAS, canonical order-independent digests, atomic complete
grant replacement and drift repair. No authoritative Corpora entitlement provider
exists in this repository; ownership/freshness verification and production provider
wiring remain explicit application responsibilities. Added mandatory UUID session_id
claims and per-operation auth.sessions subject/deadline checks to PostgreSQL adapters.
Deleted, mismatched and expired sessions fail without relying on JWT expiration alone.
No auth session mutation or application authentication middleware change was made.

Verification: 1006 passed, 34 skipped, including 24 real PostgreSQL tests. New tests
cover session deletion/expiry/subject mismatch, missing session claims, admin-only
synchronization, provider takeover/CAS rejection, order-independent retries, concurrent
initial adoption, drift repair and complete grant rollback on failed synchronization.
Ruff passes; mypy passes for 121 files; graph conformance passes seven tests/25 fixtures.
Both wheels build. Actual-wheel isolated imports away from checkout pass, including
canonical entitlement digest checks; core remains free of psycopg. Umbrella verification
uses the documented existing auth import dependencies rather than a full app install.
Existing Starlette/httpx warning remains. Disposable loopback PostgreSQL was removed.
Supabase session documentation was consulted; tests use fixture auth tables, not a live
project. No push, merge, deployment or production migration occurred. Session checks
operate at request start; GoTrue refresh/inactivity/single-session policy evaluation
and a production verified entitlement provider remain outside this bounded slice.

# Scholarly citation intake follow-up

Added a lightweight scholarly recognizer protocol, exact mention model, portable
CitationDiscovery records and catalog intake preserving unknown/unavailable/ambiguous
work outcomes. Identified hypotheses use ordinary unresolved pending References;
exact passage retrieval remains a separate Resolver operation. No scholarly parser,
network dependency, guessed work identity or discovery database integration is claimed.
The synthetic example emits intact unknown/ambiguous records and verifies a mapped
passage through the existing snapshot resolver.

Verification: 1017 passed, 34 skipped (11 new scholarly tests; 24 real PostgreSQL
integration tests still pass). New tests cover unknown/ambiguous/unavailable catalog
outcomes, Unicode spans, stale quote/context/stream/normalization rejection, catalog
passage-identity contract violations, wire attempts to self-approve/invent hypotheses,
JSON identity preservation and actual example retrieval. Ruff passes; mypy passes for
123 files; graph conformance passes seven tests/25 fixtures. Both wheels build.
Standalone actual-wheel example execution away from checkout passes with Pydantic
only and no psycopg; umbrella actual-wheel imports pass. Example JSON is available
at `/tmp/reference-linking-scholarly-demo.json`. The disposable PostgreSQL container
was removed. Existing Starlette/httpx warning remains. No push, merge, deployment,
external publication or live database changes occurred. Unknown discovery persistence
and retry/review integration remain staged explicitly in scholarly.md.

# Offline scholarly discovery management follow-up

Added SQLite discovery registration/history, semantic event fingerprints preserving
original IDs on retries, explicit catalog refresh with stable work-hypothesis IDs,
rejection and atomic work selection creating an ordinary pending/unresolved Reference.
Unknowns and unchosen ambiguous hypotheses remain in discovery history. Complete
original/converted mappings remain attached to discovery revisions; overlapping maps
are retained as evidence on the selected working Reference without projecting bounds.
The adapter trusts local caller actors and introduces no PostgreSQL tables/routes.

Verification: 1026 passed, 34 skipped, including nine new discovery tests and the
existing 24 real PostgreSQL tests. Coverage includes durable unknown/rejected records,
retry preservation, ID stability through catalog disappearance/reappearance, stale
sources/versions and changed-event rejection, concurrent retries/selection, retained
mapping evidence, atomic rollback on forced selection failure and the walkthrough.
Ruff passes; mypy passes for 125 files; graph conformance passes seven tests/25 fixtures.
Both wheels build. The actual installed umbrella wheel runs the complete discovery
walkthrough away from checkout in a fresh environment with Pydantic only; isolated
core wheel import also passes without psycopg. Example JSON is available at
`/tmp/reference-linking-discovery-review-demo.json`. Disposable PostgreSQL was removed.
Existing Starlette/httpx warning remains. No push, merge, deploy, live database changes
or external publication occurred. PostgreSQL discovery authorization/persistence and
production converter wiring remain staged.

# PostgreSQL scholarly discovery follow-up

Added PostgreSQL discovery registration/history, catalog refresh and reviewer-only
work selection using the same pure decisions/fingerprints as SQLite. Every operation
checks sessions, membership and retained resource scopes. Advisory locks serialize
registration/CAS; selection and pending working-reference creation commit together.
Tests cover concurrent retries/choices, capability denial, source revocation, tenant
isolation and forced selection failure rolling back the working reference. Schema
additions remain an unapplied proposal; no production database was modified.

# Native adapters, application integration and extraction completion

Implemented typed PDF quads/native quote selectors, optional PyMuPDF glyph extraction
and crop/rotation transforms, bounded EPUB CFI generation/retrieval, multi-node HTML
ranges and an explicit browser capture bridge. Added opt-in authenticated FastAPI
composition over trusted inventory/catalog/entitlement inputs, conversion and scholarly
recognizer hooks, manual review/retrieval, server-reconciled imports and approved
exports. C-USX insertion preserves text/inline structure with matching UUID link IDs
and advertised paired-boundary anchors; native structural retrieval checks range
pairs. Separate admin/provider receipts retain per-destination delivery/removal
claims without converting editorial acknowledgment into proof. Their table/indexes
remain part of the unapplied schema proposal outside migrations.

Final verification: **1047 passed, 34 skipped**, including **35 real PostgreSQL tests**
against disposable loopback PostgreSQL 17. The subsequent schema index addition was
verified by rerunning all 35 PostgreSQL tests. Ruff passes and mypy passes for 135
source files. Existing Corpus Document conformance passes seven tests/25 indexed
fixtures with JSON/XML round trips. Both core and umbrella wheels build. Browser
capture JavaScript passes Node's syntax check; browser capture correspondence is
exercised through the HTTP adapter with matching/mismatched tree fixtures, not a
claim of end-to-end browser rendering coverage.

A standalone source export builds both sdist and wheel independently. Its installed
wheel passes the actual 38 detector/resolver/scholarly tests in a fresh environment
away from the repository with Pydantic as the only library dependency (pytest is
installed for verification). Isolated import confirms neither corpora_py nor psycopg
is installed there. A fresh umbrella wheel installation with explicitly provided
adapter/shared utility dependencies passes ten native/C-USX tests away from checkout
and imports the HTTP runtime and receipt adapter. This is an adapter-focused smoke
installation, not a verification of every umbrella dependency/application feature.

Inspectible local artifacts: `/tmp/reference-linking-final-dist`,
`/tmp/corpora-linking-source-final-dist`, `/tmp/corpora-linking-source-final-verified`
and `/tmp/reference-linking-final-tests.txt`. Source extraction is reproducible via
`bin/build/export_linking.py`. Version 0.1.0 remains provisional/unpublished; no new
release automation was added. The existing Starlette/httpx deprecation warning
remains. See [production capabilities/limits](production.md) for unsupported format
variants and real inventory/policy/provider configuration required before rollout.
No push, merge, deployment, PyPI publication, remote delivery or live Supabase
modification occurred. The disposable database container was removed after checks.
