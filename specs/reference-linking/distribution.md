---
title: Reference linking distribution and runtime decision
description: Homebrew release dependency, open-source repository boundary and web runtime recommendation.
tags: [references, distribution, runtime]
status: proposed
---

# Recommendation

Publish the reusable MIT core from a separate `exegia/corpora-linking` repository
when its release review is complete. Keep authenticated storage, entitlement policy,
C-USX integration and heavyweight file adapters in Corpora. For `corpora-web`, use
a typed TypeScript client calling the authenticated Python HTTP API. Vercel can
host its short request operations; local Python is the CLI/desktop/offline path.
Browser Python is an optional later experiment, not the working-reference authority.
No repository creation, remote push, deployment, release or announcement has been
performed as part of this investigation.

# Evidence from the repositories

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
The extraction tool already produces portable source, examples, instructions and
38 core tests. A separate repository gives this public contract its own issues,
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

The current corpora-py wheel **bundles corpora_linking**. Installing an independent
corpora-linking wheel beside it gives two distributions ownership of the same files;
uninstalling/upgrading either can damage the other. Before independent consumption:

1. Extract/export the public core and validate its standalone wheel/sdist/tests.
2. Choose the public repo/package name, maintainer ownership and compatibility policy.
3. Prepare a coordinated Corpora release that removes the bundled core from its
   Hatch wheel package list and depends on the separately released core version.
4. Keep the workspace source for development, but test installed distributions with
   exactly one owner of corpora_linking. Verify upgrades/uninstalls in clean envs.
5. Update CLI dependency constraints against actual released artifacts and regenerate
   locks; keep API/adapter/core versions demonstrably compatible.

Until then, keep the existing bundled wheel path. No separate package should be
silently added to Homebrew dependency resolution.

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
> [Public repository and installation links after release]

# Next implementation sequence

1. Review the prepared Homebrew CLI changes and the namespace/repository decision.
2. Prepare the public extraction/release transition without dual namespace ownership.
3. Add corpora-web's app/lib/references client and seam tests using its existing
   session/config conventions; do not rewrite its SPA deployment model.
4. Connect an authorized document snapshot/link index provider. The current linking
   API has no reference-list or document-download route; do not assume those exist.
5. Add selection/preview/save/open UI, then separate review/publication states.
6. Validate the deployment build's dependencies and controlled test database setup.
7. Roll out/release/announce only through separately authorized release actions.

# Primary design/runtime sources

- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
- [Pyodide package loading](https://pyodide.org/en/stable/usage/loading-packages.html)
- [Micropip wheel compatibility](https://micropip.pyodide.org/en/stable/project/usage.html)
- [react-py API and worker lifecycle](https://elilambnz.github.io/react-py/docs/introduction/api-reference)
- [react-py project](https://github.com/elilambnz/react-py)
- [Core extraction and current production integration](production.md)

# Local verification

The Homebrew CLI feature branch passes all 67 Python tests, including nine
reference command tests. Ruff lint/format checks pass; the CLI wheel builds and
its installed code retrieves the exact selection and rejects a changed revision
when executed away from checkout with the local linking-enabled dependencies.
The real v2.1.0 release tarball and its VERSION/checksum were verified for the
separate formula fix. Homebrew/macOS audit and install tests could not run because
brew and Ruby are unavailable in this workspace. The corpora-py repository's
Ruff/mypy checks pass; no corpora-web application code was modified during this
investigation. No release, announcement, deployment or remote write occurred.
