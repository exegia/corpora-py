<div align="center">

# corpora-py

[![CI](https://img.shields.io/github/actions/workflow/status/exegia/corpora-py/pr.yml?branch=dev&label=ci)](https://github.com/exegia/corpora-py/actions/workflows/pr.yml)
[![PyPI](https://img.shields.io/pypi/v/corpora-py)](https://pypi.org/project/corpora-py/)
[![Python](https://img.shields.io/pypi/pyversions/corpora-py)](https://pypi.org/project/corpora-py/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**📚 Turn any book into a queryable text graph — then let an AI read it with you.**

One process serves an MCP server, a document→corpus conversion pipeline, and a
citation resolver over every [Context-Fabric](https://context-fabric.ai) corpus you own.

[Quick start](#-quick-start) · [MCP tools](#-mcp-tools) · [References](#-reference-identifiers) · [Architecture](docs/architecture/context-fabric/README.md) · [Workflow](.github/WORKFLOW.md)

</div>

---

## Overview

Feed it an EPUB, a PDF, a TEI edition or a Text-Fabric dataset; get back a
`.corpus` archive whose every word, clause, verse and chapter is a typed node in
a queryable graph. Then read it, search it, cite it, and hand it to Claude —
over HTTP or over the Model Context Protocol, from the same process.

```
EPUB · HTML · XML · TEI · PDF · text · .tf zip
        │
        ▼  POST /convert            (background job)
   Text-Fabric  →  .cfm cache  →  .corpus archive
        │                              │
        ▼  /mcp (30 tools)             ▼  /storage (Hugging Face Hub or Supabase)
   AI clients                     /refs · /convert/{id}/… · /validate
```

| Surface | Path | What it does |
|---|---|---|
| **MCP server** | `/mcp` | 30 tools for AI clients (Claude Desktop, browser agents, …) |
| **Conversion** | `/convert` | Upload a document → background job → `.corpus`, plus a per-job read/annotate/version layer |
| **Ingestion** | `/ingest` | Docling → Context Fabric v1 canonical `graph.json` (needs the `docling` extra) |
| **Validation** | `/validate` | Confirm a dataset round-trips `.tf → .cfm → mmap` before you trust it |
| **Storage** | `/storage` | Publish/list/read `.corpus` archives on the Hub, with manifest + annotation edits and version history |
| **References** | `/refs` | `bhsa@2021/Deut:4:2!clause1` ⇄ node, plus label/pill/share-URL bundles |
| **AI curation** | `/ai` | ⏳ Contract-first stub — every route answers `501` until [#214](https://github.com/exegia/corpora-py/issues/214) lands |
| **Health** | `/health`, `/capabilities` | Liveness, and what this deployment lets a client actually do |

---

## 🚀 Quick start

```bash
pip install corpora-py     # or: uv add corpora-py
corpora-api                # MCP + conversion + storage + refs on :8000
```

```bash
# Convert a book (auth off for a local trial run)
AUTH_REQUIRED=false corpora-api &
curl -F 'file=@commentary.epub' localhost:8000/convert          # → {"job_id": "..."}
curl localhost:8000/convert/<job_id>                            # → status
curl -O -J localhost:8000/convert/<job_id>/download             # → commentary.corpus
```

Or point an MCP client straight at a Text-Fabric dataset on disk, with no HTTP
app at all:

```bash
cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA        # stdio, for Claude Desktop
cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA --sse 8000   # or --http 8000
cf-mcp --corpus …/BHSA --name BHSA --corpus …/GNT --name GNT    # several at once
```

### Development install

```bash
git clone https://github.com/exegia/corpora-py && cd corpora-py
make setup          # uv sync + dotenvx + example deps + embedded Python
make test           # 719 tests
make ci             # what a PR runs: sync + lint-check + test
make help           # every other target
```

> **Only `corpora-py` is published to PyPI.** Its wheel bundles the source of
> `corpora-common`, `corpora-mcp` and `corpora-admin`, so `pip install corpora-mcp`
> (or `-admin`, or `-common`) is intentionally not a thing — install `corpora-py`
> and import `corpora_mcp` / `admin` / `common` from it. The three stay separate
> workspace members for local dev and independent builds.

---

## 🧰 MCP tools

The combined app registers **30 tools**; a public read-only deployment
(`HF_READ_ONLY=true`) registers **26**, because the four write tools are never
registered rather than left to fail. A standalone `cf-mcp` process registers the
**15** that need no admin/Hub dependency.

| Category | Tools | `cf-mcp` |
|---|---|:---:|
| **Discovery** | `list_corpora` · `describe_corpus` · `list_features` · `describe_feature` · `get_text_formats` | ✅ |
| **Search** | `search` · `search_continue` · `search_csv` · `search_syntax_guide` | ✅ |
| **Read** | `get_passages` · `get_node_features` | ✅ |
| **Validate** | `validate_corpus` | ✅ |
| **References** | `reference_create` · `reference_resolve` · `reference_shortcode` | ✅ |
| **Hub storage** | `storage_list_corpora` · `storage_corpus_info` · `storage_download_corpus` · `storage_upload_corpus`\* · `storage_delete_corpus`\* | — |
| **Stored corpus detail** | `corpus_sections` · `corpus_index` · `corpus_content` · `corpus_node_get` · `corpus_manifest_get` · `corpus_manifest_update`\* · `corpus_node_annotate`\* | — |
| **Stored corpus refs** | `corpus_reference_create` · `corpus_reference_resolve` · `corpus_reference_shortcode` | — |

\* Write tools — skipped entirely when `HF_READ_ONLY=true`.

### Recommended agent workflow

```
describe_corpus()           → what node types exist
list_features()             → what annotations are available
search_syntax_guide()       → learn the query language
search(template, "count")   → check scale before fetching
search(template, "results") → paginated result set
get_passages(references)    → read the matched text
reference_create(node)      → a citation someone can store and resolve later
```

### Programmatic use

```python
from corpora_mcp import mcp
from corpora_mcp.corpus import corpus_manager

corpus_manager.load("~/.exegia/datasets/bibles/BHSA", name="BHSA")
mcp.run(transport="sse", host="localhost", port=8000)
```

---

## 🔗 Reference identifiers

One schema-agnostic grammar cites any node in any corpus — book/chapter/verse and
volume/chapter/paragraph alike, because the section path is whatever the corpus
declares in `T.sectionTypes`:

```
[corpus[@version]/]Sec1[:Sec2…][!<otype><i>[-<j>]]      bhsa@2021/Deut:4:2!clause1
urn:tf:<corpus>[@version]:Sec1[:Sec2…][!…]              urn:tf:kjv:Gen:1:1
                                                         mobydick@1.0/Moby-Dick:3!word12
```

```bash
curl 'localhost:8000/refs/resolve?ref=bhsa@2021/Deut:4:2!clause1'
# → node + section path + corpus metadata + a compact `token` serialization
```

Two rules make it deterministic: a node is addressed from the section holding
its **first slot** (so a clause spilling into the next verse is counted once),
and `@version` is optional on input but always emitted on output — a pinned
version that isn't loaded gets a `409` rather than a wrong node.

- `common.utils.tfref` — grammar + resolution (byte-identical to
  [`skills/tf-reference-id/scripts/tfref.py`](skills/tf-reference-id); edit one, copy the other)
- `common.utils.refdisplay` — label (`Deut 4:2 · clause 1`), pill (`Deut 4:2 cl1`), share URL
- `common.utils.refcompact` — the compact positional token (`cobhsa_bk005_ch004_pa002_cl001`)
  as a *serialization*, not a second citation form
- Decision record: [docs/architecture/reference-forms.md](docs/architecture/reference-forms.md)

---

## 📦 Converting documents

| Format | Parser | Converter | Notes |
|---|---|---|---|
| EPUB | `EpubParser` | `convert_epub_to_tf` | one `chapter` per spine document |
| HTML | `HtmlParser` | `convert_html_to_tf` | one `document` node wrapping top-level elements |
| XML | `XmlParser` | `convert_xml_to_tf` | generic element tree |
| TEI | `TeiParser` | `convert_tei_to_tf` | one node per top-level `<div>` |
| TEI (zip) | `TeiParser` | `convert_tei_zip_to_tf` | multi-file TEI editions |
| PDF | `PdfParser` | `convert_pdf_to_tf` | one `page` node per page |
| Plain text | `PlainTextParser` | `convert_text_to_tf` | one `paragraph` per blank-line block |
| Text-Fabric zip | — | `convert_tf_zip_to_tf` | re-package an existing `.tf` dataset |

Over HTTP (recommended for anything large — a full Bible pins a core for
minutes, which is why `/convert` is job-based) or directly in Python:

```python
from admin.converters import CONVERTERS, convert_to_corpus
from admin.parsers import SourceFormat

tf_dir = CONVERTERS[SourceFormat.EPUB]("commentary.epub", "out/commentary.tf")
convert_to_corpus(tf_dir, "commentary.corpus", name="MyCommentary", language_code="en")
```

Once a job succeeds, its result is readable *before* you publish it —
`/convert/{id}/sections`, `/index`, `/content`, `/nodes/{n}`, `/manifest` — and
editable, with `/versions`, `/diff` and `/restore` over the archive's own git
history. The same layer (minus `/diff`) covers published archives under
`/storage/{filename}/…`. See [`packages/admin/README.md`](packages/admin/README.md).

---

## ⚙️ Configuration

`pydantic-settings` loads `.env.{ENVIRONMENT}` (default `.env.development`),
resolved at import time by `common/utils/constant.py`. `.env.*` files are
encrypted with `dotenvx` — use `dotenvx run -- <cmd>` outside `uv run`.

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_REQUIRED` | `true` | Require a Supabase JWT on every path but `/health`, `/capabilities`, `/`, docs |
| `PROJECT_REF` / `SUPABASE_JWKS_URL` | — | Where to fetch the JWKS that verifies those tokens |
| `HF_READ_ONLY` | `false` | Refuse every Hub write (403 on REST, write MCP tools unregistered) |
| `HF_STORAGE_REPO` / `HF_TOKEN` | — | Hub repo backing `/storage`, and its token |
| `STORAGE_BACKEND` | `huggingface` | `supabase` swaps the library backend |
| `JOB_STORE` | `memory` | `supabase` shares conversion-job state across instances |
| `REFERENCE_URL_TEMPLATE` | `/refs/resolve?ref={ref}` | Share-link shape for reference pills |

### Auth

Every path except `/health`, `/capabilities`, `/` and the docs requires
`Authorization: Bearer <supabase-jwt>` — or `?token=` for the
`/convert/{id}/ws` WebSocket, since browser `WebSocket` clients can't set
headers. It's a raw ASGI middleware (`corpora_py.auth.AuthMiddleware`), not a
`Depends`, because `Depends` never sees the mounted `/mcp` sub-app or WebSocket
scopes. With `AUTH_REQUIRED=true` and no JWKS configured, requests fail
**closed** (401), not open.

`HF_READ_ONLY` is deliberately decoupled from `AUTH_REQUIRED`: a public demo
runs `AUTH_REQUIRED=false` **and** `HF_READ_ONLY=true`, so anonymous visitors
convert, read and query while the Hub stays untouchable. Local dev stays fully
writable.

---

## 🐳 Docker

```bash
# Combined app (MCP + conversion + storage + refs)
docker build -f dockerfiles/Dockerfile -t corpora-py .
docker run -p 8000:8000 -v ~/.exegia/datasets:/data/datasets:ro corpora-py

# MCP only — no text-fabric/admin weight
docker build -f dockerfiles/Dockerfile.client -t corpora-mcp .
docker run -p 8000:8000 -v ~/.exegia/datasets:/data/datasets:ro \
  corpora-mcp cf-mcp --corpus /data/datasets/BHSA --name BHSA --sse 8000

# Or Compose
docker compose -f dockerfiles/docker-compose.yml up corpora
```

The app also deploys to Vercel Functions (Python runtime) — see the root
`CLAUDE.md` for the bundle-size rules, and note that long conversions there hit
the function timeout, which is what the container image is for.

---

## 🧱 Workspace

A **uv workspace** of three packages plus an umbrella:

| Package | Source | Purpose |
|---|---|---|
| `corpora-common` | `packages/common/src/common/` | Settings, logging, JWT verification, reference grammar, Context Fabric JSON Schemas |
| `corpora-mcp` | `packages/mcp/src/corpora_mcp/` | FastMCP server + `cf-mcp` CLI + `CorpusManager` |
| `corpora-admin` | `packages/admin/src/admin/` | Parsers, converters, ingestion, and every HTTP/MCP admin surface |
| `corpora-py` | `src/corpora_py/` | Umbrella: combines the above into one FastAPI app (`corpora-api`) |

`corpora_mcp` is *not* importable as `mcp` — that name belongs to the official
MCP SDK that `fastmcp` itself depends on.

> **Not in `common`, despite older docs:** there is no `common.auth`, no Supabase
> *client*, no git-based dataset fetcher, and no `common.models` / `common.schemas`
> module. `common` has `utils/` (settings, logging, `jwt_auth`, `tfref`,
> `refdisplay`, `refcompact`, request context) and `schemas/` (the Context Fabric
> v1 JSON Schemas). Supabase appears as a JWT *issuer*, plus two opt-in
> server-side backends (`STORAGE_BACKEND`, `JOB_STORE`) that talk REST — not via
> the `supabase` SDK. Don't write code assuming the older modules exist.

```
corpora-py/
├── pyproject.toml              # workspace root + umbrella; corpora-api / cf-mcp entry points
├── makefile                    # every CI step is a target (make help)
├── bin/                        # the shell scripts those targets call
├── packages/
│   ├── common/src/common/      # utils/ + schemas/context_fabric/v1/
│   ├── mcp/src/corpora_mcp/    # server.py · corpus.py · reference.py · validate.py
│   └── admin/src/admin/
│       ├── parsers/            # source format → shared Document/Unit schema
│       ├── converters/         # Document/Unit → Text-Fabric → .cfm → .corpus
│       ├── ingest/             # Docling → Context Fabric v1 graph
│       └── services/           # /convert /ingest /validate /storage /refs + MCP twins
├── src/corpora_py/             # app.py · auth.py · ai/ (501 stub) · bridge.py
├── skills/tf-reference-id/     # the reference grammar as an agent skill
├── docs/architecture/          # Context Fabric v1 spec series + decision records
├── example/                    # React Router 8 + Electrobun demo app (see example/README.md)
├── supabase/migrations/        # tables for the optional Supabase job store / storage
└── dockerfiles/                # combined · MCP-only · admin-only images
```

---

## 🔀 Branching, CI, and releases

Full details in [`.github/WORKFLOW.md`](.github/WORKFLOW.md).

```
feat/add-parser ──PR──> dev ──(daily/manual)──> next ──cut──> release/vX.Y.Z ──PR──> main
                  (deleted on merge)          (preview)                      (tag + PyPI)
```

| Flow | What happens |
|---|---|
| `<type>/<slug>` → PR to `dev` | `guard` (branch name + conventional-commit PR title), `check` (`make ci`), AI review once ready |
| **Promote to next** (22:00 UTC or manual) | Opens `dev` → `next`, version classified from churn (`<100` patch, `100–999` minor, `≥1000` major), auto-merges on green |
| Push to `next` | Vercel preview; cuts/refreshes `release/vX.Y.Z`; opens or updates the draft PR into `main` |
| `release/vX.Y.Z` → PR to `main` | `guard` also asserts `pyproject.toml` matches the branch version; `package` uploads the wheel |
| Release PR merged | Tags `vX.Y.Z` → PyPI (OIDC trusted publishing) + sidecar bundles; syncs `main` back into `next` and `dev` |

Exactly one release branch is in flight at a time. Retitling a red PR does **not**
re-run the guard (`pr.yml` doesn't fire on `edited`) — close and reopen it.

---

## Related

- **[exegia/corpora-cli](https://github.com/exegia/corpora-cli)** — the `corpora`
  terminal CLI + TUI (convert/validate/library), installed from Homebrew:
  `brew tap exegia/corpora-cli https://github.com/exegia/corpora-cli && brew install corpora`
- **[`example/`](example/README.md)** — the React Router 8 + Electrobun app that
  drives this API, deployed at [corpora-py-example.vercel.app](https://corpora-py-example.vercel.app)
- **[Context Fabric v1 spec](docs/architecture/context-fabric/README.md)** — the
  canonical content graph these converters are migrating toward

## License

[MIT](LICENSE)
