---
title: Reference linking distribution and runtime decision
description: Homebrew release dependency, open-source repository boundary and web runtime recommendation.
tags: [references, distribution, runtime]
status: implemented
---

# Recommendation

The reusable MIT core is published as
[`corpora-linking 0.1.0`](https://pypi.org/project/corpora-linking/0.1.0/) from
[exegia/corpora-linking](https://github.com/exegia/corpora-linking). GitHub trusted
publishing succeeded and a fresh PyPI install passed all 65 core tests and examples.

This feature branch migrates Corpora to `corpora-linking>=0.1.0,<0.2`, removes
the local core source/workspace package and excludes the core namespace from
the umbrella wheel. Native adapters, authentication, review storage and C-USX
remain in Corpora. The Homebrew CLI declares the same released dependency
directly; its offline commands need no new umbrella version. Both lockfiles
resolve real PyPI artifacts. The CLI/formula still need their normal release.

For corpora-web, use a typed client of the authenticated Python HTTP API.
No live database changes, production deployments or social-media posts were made.

# Evidence before the dependency migration

- GitHub resolves `exegia/corpora-cli` to repository ID 1346786320,
  `exegia/homebrew-corpora`. It is the canonical CLI source AND the Homebrew tap.
  Changes belong there once, not in both clones.
- The tap installs its own CLI-tag tarball from Formula/cli.rb; pip resolves
  `corpora-py>=2.2.0`. The formula currently points at v1.2.1, while the inspected
  dev lane is the released v2.1.0 tree. That existing formula lag is separate from
  this unreleased linking feature. A separate local fix/cli-formula-v2-1-0 worktree
  now points at the real v2.1.0 tarball after verifying its VERSION and SHA-256
  df5d9a0fb21689fe5f3e823c66db195eff6a1e78977a590ec3d73e6ce87bdae3.
  It is prepared for review, not pushed or applied to the public tap.
- PyPI's latest corpora-py is 5.0.0. Inspecting that actual wheel shows no
  `corpora_linking` package and no `corpora_py/linking_api.py`. The local feature
  wheel also labels itself 5.0.0, so version equality does not prove availability.
  A real release must receive a new version above the existing published release.
- The Homebrew feature branch adds lazy `references check` and `references retrieve`
  commands with exact offline validation. Published dependencies remain installable;
  missing linking core yields a clear error. The release sequence is in the tap's
  docs/reference-linking.md. No invented dependency floor or unreleased PyPI name
  was introduced.
- corpora-web is a static React Router SPA on Vercel. Its existing API seam uses
  `VITE_CORPORA_API_URL` (default https://api.exegia.co) and attaches the Supabase
  access token when present. Routes import app/lib helpers rather than SDKs.
  Its current conversion contract says the Python service is compute-only; linking
  is an explicit new service boundary with authoritative PostgreSQL working state.
  This change must be documented rather than assuming conversion storage semantics
  apply to references.
- corpora-py's Vercel build currently excludes some heavyweight dependencies and
  does not install the optional linking-postgres/PyMuPDF extras. Linking remains
  disabled by default. Existing deployed API availability is not proof that these
  new routes work in production.

# Why a separate open-source repository makes sense

The core already builds independently, uses only Pydantic, performs no I/O, has
an MIT license, preserves stable reference IDs and retains unresolved evidence.
It supports two creation workflows through one model, conservative exact selection
verification, bounded Bible detection and scholarly recognizer/catalog/resolver
ports. Other reading apps can use it without adopting Corpora's database or UI.
The released package includes portable examples and 65 tests.
The separate repository gives this public contract its own issues,
version policy, documentation and release history.

Keep these boundaries explicit:

| Public core repository | Corpora integration |
|---|---|
| Source/target/reference models and typed locators | Supabase/PostgreSQL sessions, grants and review history |
| Exact scalar quote/context verification | Asset inventory and entitlement providers |
| Bible detector and scholarly intake ports | Configured production recognizers and conversion jobs |
| Offline catalog/resolver values and protocols | C-USX/graph transport mappings and publication receipts |
| Synthetic fixtures, MIT license, examples | pdfplumber, EbookLib/lxml, optional PyMuPDF and browser bridges |

Native adapters could later become separately named integration packages, after
format coverage and dependency licensing are reviewed. Do not describe PyMuPDF's
AGPL/commercial dependency as part of the MIT-only core. Do not claim full EPUB CFI,
Web Annotation/Readium wire compliance, general PDF layout/OCR, or a production
Supabase rollout. The supported subsets and fail-closed behavior are documented.

## Avoid owning one Python namespace twice

The new umbrella wheel contains no `corpora_linking/` files. Exactly one
distribution, `corpora-linking`, owns that namespace. Development imports use
the same PyPI package as installed wheels; changes to core source belong in
the independent repository. Integration examples/tests remain in Corpora.

The published corpora-py 5.0.0 has no linking source. Local feature artifacts
still carry the dev-lane version for testing only; the release lane must assign
a new version before publication. Never replace the existing PyPI 5.0.0.
A root release merge also triggers production Vercel deployment and requires
that deployment to be within the authorized scope.

# Runtime comparison

| Option | Suitable work | Decision |
|---|---|---|
| Python HTTP API, optionally Vercel | Authenticated save/history/review/import/export; exact retrieval with trusted inventory | Recommended for the web app |
| Local Python sidecar/in-process CLI | Local files, native parsing, offline SQLite and developer tests | Recommended for desktop/CLI; web still calls its configured server |
| Pyodide worker | Optional local core model/quote checks or offline discovery experiments | Explore only after testing the exact WASM dependency set |
| react-py | React hooks/provider around Pyodide workers | Useful for a Python playground; adds no server authority or native CPython compatibility |

Vercel currently supports Python 3.13, matching the project floor. Its documented
standard Python bundle limit is 500 MB uncompressed and Python has no automatic
runtime tree-shaking. Duration and larger-function options depend on plan/runtime;
inspect actual deployment artifacts rather than inferring size from the wheel.
The existing maxDuration=300 configuration is not an invitation to run every large
PDF conversion inside a reference-review request.

For the first web integration, keep request operations short, use a server-side
PostgreSQL connection strategy compatible with Supabase/serverless pooling and TLS,
and keep JWKS/session/resource checks at the service boundary. Fetch assets from an
authorized inventory/provider rather than bundling the whole corpus or relying on
local writable files. Do not use SQLite or in-memory state as shared cloud authority.
Move expensive extraction/OCR to the existing conversion pipeline or a job worker.
If the umbrella deploy becomes too heavy, build a thin linking-service distribution
with only the core, HTTP/auth/store dependencies and needed format adapters.

The browser holds the reader's access token and plain JSON references. DB/service-role
credentials never belong in VITE_* variables. It may preview selection text locally,
but a server revalidates it before approval/publication. The current API-fetch seam
can continue to serve conversion, while a linking-specific client rejects missing
sessions and handles 401/403/409/422/503 deliberately. Do not reuse an anonymous
conversion fallback as linking authorization.

Pyodide can install pure-Python wheels and wasm32/Emscripten wheels. Our core wheel
is pure Python, but Pydantic depends on compiled pydantic-core: a matching Pyodide
build is required. Python >=3.13, Pydantic version, core version and the Pyodide
interpreter must be tested together. Ordinary macOS/Linux wheels for psycopg,
PyMuPDF or lxml are not browser wheels. Pyodide cannot make browser-held secrets
safe or turn the browser into trusted review/publication authority. react-py wraps
this same runtime; it does not remove those constraints.

# Announcement readiness — prepare, do not post

An open-source announcement is reasonable once there is a public repository, a
released installable artifact, CI, contributor/security guidance and stable examples.
Use synthetic openly licensed data. Link the limits, explain what “resolved” proves,
and show stale/ambiguous failures as well as the happy path. Verify the actual
install command from an empty environment. Avoid “reliably links any passage” or
“production-ready” claims while unsupported native forms and inventory rollout
remain bounded.

Draft, contingent on that release:

> We're open-sourcing Corpora Linking: a small Python library for creating
> revision-aware links between passages. Manual selections and detected citations
> share the same model. Exact quote/context checks preserve stale, unknown and
> ambiguous references instead of guessing. MIT core, runnable examples and tests.
> https://github.com/exegia/corpora-linking — pip install corpora-linking

# Next implementation sequence

1. Review the Corpora integration migration and CLI dependency changes.
2. Release the CLI through its normal lanes and bump the formula to that
   real tag/checksum. Complete macOS/Linuxbrew checks in CI.
3. Prepare the new Corpora release without overwriting published 5.0.0.
   Production deployment remains a separate operational step.
4. Connect corpora-web through a typed authenticated references client, then
   supply its authoritative document snapshot and reference index provider.
5. Validate a controlled database and inventory rollout before enabling routes.

# Primary design/runtime sources

- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
- [Pyodide package loading](https://pyodide.org/en/stable/usage/loading-packages.html)
- [Micropip wheel compatibility](https://micropip.pyodide.org/en/stable/project/usage.html)
- [react-py API and worker lifecycle](https://elilambnz.github.io/react-py/docs/introduction/api-reference)
- [react-py project](https://github.com/elilambnz/react-py)
- [Core extraction and current production integration](production.md)

# Local verification

Against the published core, Corpora Ruff/mypy checks pass and the suite has
1,013 passing tests with 68 skips. An additional disposable loopback PostgreSQL
run passes all 35 reference authorization/history/API tests; no live service is
used. The CLI passes all 67 tests without skipping its core tests.

Built wheel/sdist inspection confirms no umbrella core files and a declared
standalone runtime dependency. A fresh installed-wheel environment passes 93
portable core/store/publication/CLI tests away from the source checkout.
Uninstall/reinstall checks verify that removing the umbrella preserves the core.
Homebrew tooling is unavailable locally; the tap's macOS CI must verify it.
