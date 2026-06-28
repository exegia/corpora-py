# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (also installs dotenvx for encrypted .env)
uv run scripts/setup.py

# Run tests
uv run pytest

# Run a single test file or test
uv run pytest path/to/test_file.py::test_name

# Build wheel
uv build --out-dir dist/

# Publish (bump patch/minor or explicit version)
uv run scripts/publish.py          # patch
uv run scripts/publish.py minor
uv run scripts/publish.py 1.2.3

# Clean caches and build artifacts
uv run scripts/clean.py

# Start MCP server (stdio — for Claude Desktop)
uv run cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA

# Start MCP server (SSE on port 8000 — for remote clients)
uv run cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA --sse 8000

# Multiple corpora
uv run cf-mcp \
  --corpus ~/.exegia/datasets/bibles/BHSA --name BHSA \
  --corpus ~/.exegia/datasets/bibles/GNT  --name GNT
```

## Architecture

This is a Python library (published as `corpora-py`) — no web server, just an MCP server entry point and importable modules.

Code is organized into decoupled workspaces under `src/`:

- `shared/` — code used by both admin and client (auth, supabase, models, schemas, constants, git fetcher, epub parser)
- `client/` — client/consumer surface (FastMCP server + query tools for AI + desktop apps)
- `admin/` — admin / full-feature tooling (conversion pipelines that need text-fabric)

### Module layers (post-refactor)

**`client.mcp`** — The primary user-facing surface. A FastMCP server exposing 11 tools to AI clients (Claude Desktop, etc.). The `cf-mcp` CLI entry point lives here. `corpus.py` holds the singleton `CorpusManager` that loads/manages `context-fabric` (`cfabric.Fabric`) corpora at runtime.

**`shared.supabase`** — Low-level layer. `client.py` creates a single synchronous Supabase client using the service-role key (bypasses RLS; no per-user session stored). `authentication.py` provides thin, typed wrappers around `supabase.auth.*` methods.

**`shared.auth`** — High-level application layer on top of `shared.supabase`. After any sign-in that produces a session, it checks whether a matching `public.users` record exists and returns a `SignInResult` or `CurrentUser` dataclass. All per-user context is passed explicitly via JWT/token args — the Supabase client is stateless with respect to sessions.

**`shared.corpus`** — Git-based dataset fetcher. Shallow-clones a repo and locates Text-Fabric dataset directories (those containing both `otext.tf` and `otype.tf`).

**`admin.utils`** — EPUB/HTML → Text-Fabric converters (and related packaging). These produce a node hierarchy and are part of the admin/full extra. Text-fabric is optional via `[full]`.

**`shared.models` / `shared.schemas`** — Enums, data models, and Pydantic schemas shared across modules.

### Environment / config

Config is loaded by `pydantic-settings` from `.env.{ENVIRONMENT}` (defaults to `.env.development`). The active file is resolved at import time by `utils/constant.py`. All constants are re-exported from that module.

Supabase URLs are constructed from `PROJECT_REF` (not from `SUPABASE_URL`) because the local instance runs in OrbStack:

- API (Kong): `https://supabase_kong_<project_ref>.orb.local`
- DB host: `supabase_db_<project_ref>.orb.local`

`.env.*` files are encrypted with `dotenvx`. Run `dotenvx run -- <command>` when env vars need to be decrypted at runtime outside of `uv run`.

### Corpus data flow

1. Datasets live locally under `~/.exegia/datasets/` as Text-Fabric directories.
2. `CorpusManager.load(path)` wraps `cfabric.Fabric` and holds `(Fabric, api)` pairs keyed by name. (Note: the manager now lives at `client.mcp.corpus`.)
3. All 11 MCP tools call `corpus_manager.get_api(corpus_name)` to get the TF API and then use `api.S`, `api.F`, `api.T`, etc.
4. Pagination state for `search()` / `search_continue()` is held in a module-level dict with 5-minute cursor TTL.

### CI/CD

On PR merge: the `bump` job auto-increments the patch version, commits back with `[skip ci]`, and pushes a `vX.Y.Z` tag. The `build` and `publish` jobs then run against that tag, publishing to PyPI via OIDC trusted publishing (no stored token).
