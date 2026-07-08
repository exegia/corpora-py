# Corpora Platform — Python Backend

> Graph-based biblical and religious text study platform — powered by Context-Fabric, Supabase, and FastMCP.

---

## What is this?

A Python backend for studying annotated religious texts (Bible, Quran, Tanakh, commentaries, lexicons). It exposes
corpus data and conversion tooling through a combined FastAPI app:

| Surface                         | Technology                | Use case                                                                                         |
|---------------------------------|---------------------------|--------------------------------------------------------------------------------------------------|
| **MCP server** (`/mcp`)         | FastMCP                   | AI assistants (Claude, GPT, etc.)                                                                |
| **Conversion API** (`/convert`) | FastAPI + background jobs | Upload EPUB/HTML/PDF/TEI/plain-text documents and convert them to Text-Fabric/`.corpus` archives |

Corpora are loaded from [Context-Fabric](https://context-fabric.ai) — a graph-based annotated text engine. Every word,
verse, chapter, and book is a typed node in a graph with queryable features (lemma, morphology, gloss, etc.).

---

## Workspace packages

This repo is a **uv workspace** of three published packages plus an umbrella:

| PyPI package     | Source                          | Purpose                                                           |
|------------------|---------------------------------|-------------------------------------------------------------------|
| `corpora-common` | `packages/common/src/common/`   | Settings, logging, shared utilities                               |
| `corpora-mcp`    | `packages/mcp/src/corpora_mcp/` | FastMCP server + `cf-mcp` CLI                                     |
| `corpora-admin`  | `packages/admin/src/admin/`     | EPUB/HTML/PDF/TEI → Text-Fabric converters + conversion HTTP API  |
| `corpora-py`     | `src/corpora_py/` (umbrella)    | Installs all three + the combined FastAPI app (`corpora-api` CLI) |

| Module               | Purpose                                                               |
|----------------------|-----------------------------------------------------------------------|
| `corpora_mcp.server` | FastMCP server — 11 corpus tools for AI clients                       |
| `corpora_mcp.corpus` | `CorpusManager` — loads/holds Text-Fabric corpora at runtime          |
| `admin.parsers`      | Format parsers (EPUB/HTML/XML/TEI/PDF/plain) → shared schema          |
| `admin.converters`   | Parsed documents → Text-Fabric → `.cfm` → `.corpus`                   |
| `admin.services`     | FastAPI router + job manager for `POST/GET /convert`                  |
| `common.utils`       | Settings (`pydantic-settings`), logging, SSL/cert helpers             |
| `corpora_py.app`     | Combines the MCP server and admin conversion API into one FastAPI app |

> **Note:** earlier drafts of this README described `shared.auth`/`shared.models`/`shared.schemas`/`shared.corpus`
> (git-based dataset fetching, Supabase auth, Pydantic schemas). Those modules do not exist in the current `common`
> package (it currently only has `common.utils`) — they were either not carried over during the `shared`→`common`
> consolidation or are still on a roadmap. Don't rely on them until they reappear in `packages/common/src/common/`.

---

## Tech stack

- **Python 3.13+** with [uv](https://docs.astral.sh/uv/) for dependency management
- **FastMCP 2** — MCP server for AI clients
- **Context-Fabric** (`cfabric`) — graph corpus engine (fork of Text-Fabric)

---

## Getting started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) ≥ 0.9
- Python 3.13

### Install (development)

```bash
git clone <repo-url>
cd corpora-py
uv run scripts/setup.py
```

### Install a specific package

```bash
# MCP server only (lightweight)
pip install corpora-mcp

# Admin / conversion tools (includes text-fabric)
pip install corpora-admin

# Everything, including the combined FastAPI app (`corpora-api` CLI)
pip install corpora-py
```

### Environment

```bash
cp .env.example .env.development
# Fill in PROJECT_REF, SUPABASE_SECRET_KEY, etc.
```

---

## Combined FastAPI app

`corpora-api` runs a single FastAPI app that serves both the MCP server and the admin conversion API from one process
(`src/corpora_py/app.py`):

```bash
uv run corpora-api
# MCP:        http://127.0.0.1:8000/mcp
# Conversion: http://127.0.0.1:8000/convert
# Health:     http://127.0.0.1:8000/health
```

Uploading a document to `/convert` starts a background conversion job (parse → Text-Fabric → `.cfm` → `.corpus`) and
returns immediately with a job id; poll `GET /convert/{job_id}` or open `/convert/{job_id}/ws` for status. See
`packages/admin/src/admin/services/api.py` for the full endpoint list and why conversion is job-based rather than
synchronous (large documents like a full Bible can take minutes and pin a CPU core).

**Auth:** every path except `/health`/`/`/docs requires a Supabase JWT —
`Authorization: Bearer <token>` for HTTP, `?token=<token>` for the WebSocket (browser/webview `WebSocket` clients can't
set custom headers). Enforced by default (this runs as a locally-reachable sidecar, not just a dev tool); set
`AUTH_REQUIRED=false` to disable for local development. See
`src/corpora_py/auth.py` and the root `CLAUDE.md`'s "Auth" section.

---

## MCP server

The MCP server lets AI assistants query corpora directly via
the [Model Context Protocol](https://modelcontextprotocol.io). It can run standalone (`cf-mcp`, below) or mounted inside
the combined app (`corpora-api`, above) at `/mcp`.

### Start the server

```bash
# stdio — for Claude Desktop and other MCP clients
uv run cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA

# SSE on port 8000 — for remote / desktop app connections
uv run cf-mcp --corpus ~/.exegia/datasets/bibles/BHSA --sse 8000

# Multiple corpora at once
uv run cf-mcp \
  --corpus ~/.exegia/datasets/bibles/BHSA --name BHSA \
  --corpus ~/.exegia/datasets/bibles/GNT  --name GNT
```

### Docker

```bash
# Build and run the MCP-only container (no admin/text-fabric weight)
docker build -f dockerfiles/Dockerfile.client -t corpora-mcp .
docker run -p 8000:8000 \
  -v ~/.exegia/datasets:/data/datasets:ro \
  corpora-mcp \
  cf-mcp --corpus /data/datasets/BHSA --name BHSA --sse 8000

# Or run the combined app (MCP + conversion API) via the umbrella image
docker build -f dockerfiles/Dockerfile -t corpora-py .
docker run -p 8000:8000 -v ~/.exegia/datasets:/data/datasets:ro corpora-py

# Or with Docker Compose (see dockerfiles/docker-compose.yml)
docker compose -f dockerfiles/docker-compose.yml up corpora
```

### Available tools (11)

| Category  | Tool                  | Description                                              |
|-----------|-----------------------|----------------------------------------------------------|
| Discovery | `list_corpora`        | List loaded corpora and the active one                   |
| Discovery | `describe_corpus`     | Node types with counts, section hierarchy                |
| Discovery | `list_features`       | Browse features, filter by node type                     |
| Discovery | `describe_feature`    | Metadata + top values by frequency                       |
| Discovery | `get_text_formats`    | Available text encodings with samples                    |
| Search    | `search`              | Pattern search — results / count / statistics / passages |
| Search    | `search_continue`     | Paginate large result sets via cursor                    |
| Search    | `search_csv`          | Export results to a local CSV file                       |
| Search    | `search_syntax_guide` | Inline query syntax documentation                        |
| Data      | `get_passages`        | Retrieve text by section reference                       |
| Data      | `get_node_features`   | Batch feature lookup for a list of nodes                 |

### Recommended workflow for AI agents

```
describe_corpus()           → understand what node types exist
list_features()             → see what annotations are available
search_syntax_guide()       → learn the query language
search(template, "count")   → check scale before fetching results
search(template, "results") → get paginated result set
get_passages(references)    → read the matched text
```

### Programmatic use

```python
from corpora_mcp import mcp
from corpora_mcp.corpus import corpus_manager

corpus_manager.load("~/.exegia/datasets/bibles/BHSA", name="BHSA")
mcp.run(transport="sse", host="localhost", port=8000)
```

---

## Corpus datasets

Datasets are Text-Fabric archives extracted locally under `~/.exegia/datasets/`. There is currently no built-in
git-fetch helper for datasets in this repo (an earlier draft of this README described one at `shared.corpus`, which no
longer exists post-refactor) — datasets are expected to already be on disk when passed to `CorpusManager.load()` /
`cf-mcp --corpus`.

---

## Importing books (EPUB / HTML / PDF / TEI / plain text)

Documents can be converted into Text-Fabric datasets (and packaged as
`.corpus` archives) either via the HTTP API (`POST /convert`, see "Combined FastAPI app" above — the recommended path
for large documents) or directly in Python:

```bash
pip install corpora-admin
```

```python
from admin.converters import convert_epub_to_tf
from admin.converters.convert_to_corpus import convert_to_corpus

tf_dir = convert_epub_to_tf("commentary.epub", "~/.exegia/datasets/books/my-commentary/tf")
convert_to_corpus(tf_dir, "my-commentary.corpus", name="MyCommentary")
```

The converter produces this node hierarchy:

```
book
  chapter          (EPUB spine item / page)
    element        (block HTML element)
      paragraph    (paragraph-like elements)
        word       (slot — smallest unit)
```

The output directory is a valid TF dataset, loadable by the MCP server:

```bash
uv run cf-mcp --corpus ~/.exegia/datasets/books/my-commentary
```

---

## Development

### Run tests

```bash
uv run pytest
```

### Build wheels

```bash
# Individual workspace packages
uv build --package corpora-common --wheel --out-dir dist/
uv build --package corpora-mcp    --wheel --out-dir dist/
uv build --package corpora-admin  --wheel --out-dir dist/

# Bump version + publish to PyPI
uv run scripts/publish.py          # bump patch, commit, tag, push
uv run scripts/publish.py minor    # bump minor
uv run scripts/publish.py 1.2.3    # explicit version
```

### Project layout

```
corpora-py/
├── pyproject.toml          # Workspace root + umbrella package (corpora-py), corpora-api/cf-mcp entry points
├── uv.lock
├── packages/
│   ├── common/             # corpora-common
│   │   └── src/common/     #   utils/ (settings, logging, SSL cert helpers)
│   ├── mcp/                # corpora-mcp
│   │   └── src/corpora_mcp/ #  FastMCP server (server.py), CorpusManager (corpus.py), cf-mcp entrypoint
│   └── admin/              # corpora-admin
│       └── src/admin/
│           ├── parsers/     #   source format → shared Document/Unit schema
│           ├── converters/  #   Document/Unit → Text-Fabric → .cfm → .corpus
│           └── services/    #   FastAPI router + WebSocket + job manager for /convert
├── src/
│   └── corpora_py/         # Umbrella module — combined FastAPI app (app.py) + corpora-api entrypoint
├── scripts/
│   ├── setup.py            # Install deps + dotenvx + example runtime
│   ├── clean.py            # Remove caches and build artifacts
│   ├── publish.py          # Bump version + build + publish helper
│   └── build/              # Sidecar/example Python bundling scripts
├── dockerfiles/
│   ├── Dockerfile          # Combined app image (MCP + conversion API), corpora-py
│   ├── Dockerfile.client   # MCP-only image, corpora-mcp
│   ├── Dockerfile.admin    # Admin/converter-only image, corpora-admin
│   └── docker-compose.yml
└── .github/
    └── workflows/            # test/build/publish/docker CI (see .github/workflows/*.yml)
```
