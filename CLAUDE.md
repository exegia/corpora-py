# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## Commands

```bash
# Install all workspace packages in editable/dev mode
uv sync

# Install dependencies (also installs dotenvx for encrypted .env)
uv run scripts/setup.py

# Run tests
uv run pytest

# Run a single test file or test
uv run pytest path/to/test_file.py::test_name

# Build individual workspace wheels
uv build --package corpora-common --wheel --out-dir dist/
uv build --package corpora-mcp    --wheel --out-dir dist/
uv build --package corpora-admin  --wheel --out-dir dist/

# Build all workspace wheels at once (shorthand via script)
uv run scripts/publish.py          # patch bump + publish
uv run scripts/publish.py minor
uv run scripts/publish.py 1.2.3

# Clean caches and build artifacts
uv run scripts/clean.py

# Start MCP server only (stdio — for Claude Desktop)
uv run cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA

# Start MCP server only (SSE on port 8000 — for remote clients)
uv run cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA --sse 8000

# Multiple corpora
uv run cf-mcp \
  --corpus ~/.exegia/datasets/bibles/BHSA --name BHSA \
  --corpus ~/.exegia/datasets/bibles/GNT  --name GNT

# Start the combined FastAPI app (MCP at /mcp + conversion API at /convert)
uv run corpora-api

# Docker — MCP-only image
docker build -f dockerfiles/Dockerfile.client -t corpora-mcp .
docker run -p 8000:8000 -v ~/.exegia/datasets:/data/datasets:ro \
  corpora-mcp cf-mcp --corpus /data/datasets/BHSA --name BHSA --sse 8000

# Docker — admin/conversion-only image (Python API, no HTTP server)
docker build -f dockerfiles/Dockerfile.admin -t corpora-admin .
docker run -it -v ~/.exegia/datasets:/data/datasets \
  corpora-admin python -c "from admin.converters import convert_epub_to_tf; ..."

# Docker — combined app image (MCP + conversion HTTP API on :8000)
docker build -f dockerfiles/Dockerfile -t corpora-py .
docker run -p 8000:8000 -v ~/.exegia/datasets:/data/datasets:ro corpora-py

# Docker Compose (see dockerfiles/docker-compose.yml for exact service names)
docker compose -f dockerfiles/docker-compose.yml up corpora
```

## Architecture

This is a **uv workspace** of three published Python packages plus an umbrella meta-package:

| Package  | PyPI name        | Source                          | Purpose                                    |
| -------- | ----------------- | -------------------------------- | ------------------------------------------ |
| Common   | `corpora-common`  | `packages/common/src/common/`    | Settings, logging, shared utilities        |
| MCP      | `corpora-mcp`     | `packages/mcp/src/corpora_mcp/`  | FastMCP server + `cf-mcp` CLI              |
| Admin    | `corpora-admin`   | `packages/admin/src/admin/`      | EPUB/HTML/PDF/TEI → Text-Fabric converters + conversion HTTP API |
| Umbrella | `corpora-py`      | `src/corpora_py/`                | Depends on all three; combined FastAPI app (`corpora-api` CLI); used by sidecar/demo |

- **Install everything** (dev / demo / sidecar): `uv sync` or install `corpora-py`
- **Deploy only MCP server**: install `corpora-mcp` (pulls `corpora-common`)
- **Run conversion tools**: install `corpora-admin` (pulls `corpora-common` + text-fabric)
- **Deploy MCP + conversion API together**: install `corpora-py` and run `corpora-api`
- **Docker MCP-only image**: `dockerfiles/Dockerfile.client`; combined app: `dockerfiles/Dockerfile`

Code is organized into decoupled workspace packages under `packages/`:

- `packages/common/src/common/` — code used by both admin and mcp: `utils/` (`pydantic-settings`
  config, logging, SSL/cert helpers, `jwt_auth.py` — framework-agnostic Supabase JWKS
  verification, see "Auth" below). **Does not** currently include a Supabase client, sign-in
  flows, or git-based corpus fetching — see "Dropped/missing functionality" below (that's a
  different thing from request-level JWT verification, which does exist now).
- `packages/mcp/src/corpora_mcp/` — client/consumer surface (FastMCP server + query tools for
  AI + desktop apps). Named `corpora_mcp`, not `mcp` — the importable module was renamed
  because `mcp` collides with the real `modelcontextprotocol` SDK package that `fastmcp`
  itself depends on; `import mcp` inside this workspace will resolve to the SDK, not this
  package.
- `packages/admin/src/admin/` — admin / full-feature tooling: `parsers/` (source format →
  shared `Document`/`Unit` schema), `converters/` (schema → Text-Fabric → `.cfm` → `.corpus`),
  `services/` (FastAPI router + WebSocket + background job manager exposing conversion over
  HTTP — see `packages/admin/CLAUDE.md`).
- `src/corpora_py/` — umbrella package. `app.py` builds the combined FastAPI app that mounts
  the MCP server at `/mcp` and the admin conversion router at `/convert`; lives here (not in
  `admin` or `mcp`) because it's the only package that already depends on both, and putting it
  in either would create a dependency between packages that otherwise don't know about each
  other.

| Package | PyPI name | Source | Purpose |
|---|---|---|---|
| Shared | `corpora-shared-py` | `packages/shared/src/shared/` | Auth, Supabase client, models, schemas |
| Client | `corpora-client-py` | `packages/client/src/client/` | FastMCP server + `cf-mcp` CLI |
| Admin  | `corpora-admin-py`  | `packages/admin/src/admin/`  | EPUB/HTML → Text-Fabric converters |
| Umbrella | `corpora-py` | (no source) | Depends on all three; used by sidecar/demo |

**`corpora_mcp.server`** — The primary user-facing surface. A FastMCP server exposing 11 tools
to AI clients (Claude Desktop, etc.). The `cf-mcp` CLI entry point (`corpora_mcp.server:main`)
lives here. **`corpora_mcp.corpus`** holds the singleton `CorpusManager` that loads/manages
`context-fabric` (`cfabric.Fabric`) corpora at runtime.

**`admin.parsers`** — Format-specific parsers (EPUB/HTML/XML/TEI/PDF/plain text), each reducing
its source into the same `Document`/`Unit` schema (see `packages/admin/CLAUDE.md`).

**`admin.converters`** — `Document`/`Unit` tree → Text-Fabric dataset → `.cfm` cache →
`.corpus` archive. One shared TF-walker (`_walker.py`) is reused by every
`_{format}_to_tf.py` converter.

**`admin.services`** — HTTP surface over the conversion pipeline: `api.py` (upload/poll/download
via `POST/GET /convert`), `websocket.py` (`/convert/{id}/ws` coarse status push), `jobs.py`
(`JobManager` — in-process `ThreadPoolExecutor`-backed job registry; explicitly **not** safe
for a multi-worker/multi-process deployment, since job state lives in memory in one process).

**`corpora_py.app`** — Combines the above into one FastAPI app. Mounting a FastMCP ASGI app
requires forwarding its `lifespan` into the parent app or its session manager never starts;
see that module's docstring.

### Dropped/missing functionality (do not assume this exists)

Earlier revisions of this repo (and of this file) described a `shared` package with
`shared.supabase` (a synchronous Supabase client using the service-role key),
`shared.auth` (sign-in/up/out, `CurrentUser`/`SignInResult` dataclasses, JWT-based per-user
context), `shared.corpus` (a git-based Text-Fabric dataset fetcher), and `shared.models` /
`shared.schemas` (shared enums and Pydantic schemas). **None of this exists in the current
`packages/common/src/common/` tree** — it was not carried over during the `shared`→`common`
package rename/consolidation (there is no `supabase`/`auth`/`corpus`/`models`/`schemas`
submodule under `common/`, and no file anywhere in the repo references `supabase` or defines
an `auth` module). If you need this functionality, it has to be rebuilt, not just imported —
don't write code that assumes `common.auth` or similar exists without checking first.

### Environment / config

Config is loaded by `pydantic-settings` from `.env.{ENVIRONMENT}` (defaults to
`.env.development`). The active file is resolved at import time by
`common/utils/constant.py`. All constants are re-exported from that module.

`.env.*` files are encrypted with `dotenvx`. Run `dotenvx run -- <command>` when env vars
need to be decrypted at runtime outside of `uv run`.

(The previous "Supabase URLs constructed from `PROJECT_REF`" note has been removed along with
the rest of the Supabase integration — see "Dropped/missing functionality" above.)

### Corpus data flow

1. Datasets live locally under `~/.exegia/datasets/` as Text-Fabric directories.
2. `CorpusManager.load(path)` (in `corpora_mcp.corpus`) wraps `cfabric.Fabric` and holds
   `(Fabric, api)` pairs keyed by name.
3. All 11 MCP tools call `corpus_manager.get_api(corpus_name)` to get the TF API and then
   use `api.S`, `api.F`, `api.T`, etc.
4. Pagination state for `search()` / `search_continue()` is held in a module-level dict with
   5-minute cursor TTL.

### Conversion job flow (admin, exposed at `/convert`)

1. `POST /convert` streams an uploaded document to a per-job work directory and hands the
   blocking parse → Text-Fabric → `.cfm` → `.corpus` pipeline to `JobManager` (a background
   `ThreadPoolExecutor`), returning a job id immediately — conversion of a large document (a
   full Bible, a big EPUB) can take minutes and pins a CPU core the whole time.
2. `GET /convert/{job_id}` polls status; `/convert/{job_id}/ws` pushes the same status
   (queued/running/succeeded/failed) over a WebSocket as it changes. Neither reports a real
   percentage — the converters have no progress hook (see `packages/admin/CLAUDE.md`).
3. `GET /convert/{job_id}/download` serves the finished `.corpus` archive once the job
   succeeds.

### Auth (`corpora_py.auth`)

`corpora_py.app` ships as a sidecar spawned by a Tauri+Supabase desktop app — a locally
reachable port, not a public multi-tenant service, but still gated by default: every path
except `/health`/`/`/docs requires a `Authorization: Bearer <supabase-jwt>` header (or, for the
`/convert/{id}/ws` WebSocket, a `?token=` query param instead — browser/webview `WebSocket`
clients can't set custom headers on the handshake).

- **`common.utils.jwt_auth`** — framework-agnostic verification: fetches Supabase's JWKS
  (`<project_ref>.supabase.co/auth/v1/.well-known/jwks.json`, or `SUPABASE_JWKS_URL` for a
  self-hosted/local instance) via `PyJWKClient`, verifies signature + expiry + audience, raises
  `AuthError` on any failure. This is the one network dependency this otherwise-offline sidecar
  has, and only when a token actually needs checking.
- **`corpora_py.auth.AuthMiddleware`** — raw ASGI middleware (not a FastAPI `Depends`)
  applied to the whole app. `Depends` doesn't cover `app.mount("/mcp", ...)` (a plain ASGI
  sub-app, invisible to FastAPI's dependency system) or WebSocket routes
  (`BaseHTTPMiddleware`/`@app.middleware("http")` only sees `http` scope) — a raw ASGI
  middleware sitting above Starlette's router is the only thing that sees every scope type
  uniformly, which is why this isn't just a router-level dependency.
- **`AUTH_REQUIRED`** (`common.utils.config.Settings.auth_required`, default `True`) — set to
  `false` for local dev. When `True` with no JWKS URL configured (`PROJECT_REF` /
  `SUPABASE_JWKS_URL` unset), requests fail closed (401), not open.
- Decoded JWT claims land in `scope["state"]["user"]` and are used by
  `ConversionJob.is_visible_to()` (`admin.services.jobs`) to scope `GET /convert/{id}`,
  `/download`, and `/ws` to the job's own submitter (the JWT `sub` claim, recorded on the job at
  `POST /convert` time). A job created while auth was disabled has no owner and stays visible to
  everyone; a request with no claims (auth currently disabled) can see any job — ownership is
  only enforced when there's an identity on both sides to compare. Mismatches return the same
  404 as an unknown job id (not 403), so a client can't use the distinction to enumerate other
  users' job ids.

### CI/CD

On PR merge: the `bump` job auto-increments the patch version in **all** workspace
`pyproject.toml` files simultaneously, commits back with `[skip ci]`, and pushes a `vX.Y.Z`
tag. The `build` and `publish` jobs then run against that tag, building and publishing all
four wheels (`corpora-common`, `corpora-mcp`, `corpora-admin`, `corpora-py`) to PyPI via OIDC
trusted publishing (no stored token).

The `build-sidecar` workflow builds the same four wheels, then bundles them per-platform
(macOS arm64/x64, Windows) into a signed, notarized standalone Python archive for embedding
in Tauri/ElectroBun apps. The bundle step runs `python -m scripts.build --skip-build` and
resolves workspace deps from `dist/` via `--find-links` (no PyPI needed).

`.github/workflows/test.yml` runs `uv run pytest` on every push/PR — as of this writing there
are **no test files anywhere in the repo** (`tests/` doesn't exist), so this currently collects
0 items and passes trivially rather than verifying anything.
