# Corpora Platform — Python Backend

> Graph-based biblical and religious text study platform — powered by Context-Fabric, Supabase, and FastMCP.

---

## What is this?

A Python backend for studying annotated religious texts (Bible, Quran, Tanakh, commentaries, lexicons). It exposes corpus data through two surfaces:

| Surface        | Technology | Use case                          |
| -------------- | ---------- | --------------------------------- |
| **MCP server** | FastMCP    | AI assistants (Claude, GPT, etc.) |

Corpora are loaded from [Context-Fabric](https://context-fabric.ai) — a graph-based annotated text engine. Every word, verse, chapter, and book is a typed node in a graph with queryable features (lemma, morphology, gloss, etc.).

---

## Workspace packages

This repo is a **uv workspace** of three published packages plus an umbrella:

| PyPI package        | Source                         | Purpose                                              |
| ------------------- | ------------------------------ | ---------------------------------------------------- |
| `corpora-shared-py` | `packages/shared/src/shared/`  | Auth, Supabase client, models, schemas, corpus fetch |
| `corpora-client-py` | `packages/client/src/client/`  | FastMCP server + `cf-mcp` CLI                        |
| `corpora-admin-py`  | `packages/admin/src/admin/`    | EPUB/HTML → Text-Fabric converters (`[full]` extra)  |
| `corpora-py`        | *(umbrella, no source)*        | Installs all three; used by sidecar/demo             |

| Module           | Purpose                                                   |
| ---------------- | --------------------------------------------------------- |
| `client.mcp`     | FastMCP server — 11 corpus tools for AI clients           |
| `shared.corpus`  | Fetch Text-Fabric datasets from git repositories          |
| `admin.utils`    | EPUB / HTML → Text-Fabric converters (requires `[full]`)  |
| `shared.models`  | Shared enums and data model definitions                   |
| `shared.schemas` | Pydantic request/response schemas                         |
| `shared.auth`    | Auth utilities (sign-in/up/out + CurrentUser)             |

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
pip install corpora-client-py

# Admin / conversion tools (includes text-fabric)
pip install "corpora-admin-py[full]"

# Everything
pip install corpora-py
```

### Environment

```bash
cp .env.example .env.development
# Fill in PROJECT_REF, SUPABASE_SECRET_KEY, etc.
```

---

## MCP server

The MCP server lets AI assistants query corpora directly via the [Model Context Protocol](https://modelcontextprotocol.io).

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
# Build and run the MCP server container
docker build -f Dockerfile.client -t corpora-client .
docker run -p 8000:8000 \
  -v ~/.exegia/datasets:/data/datasets:ro \
  corpora-client --corpus /data/datasets/BHSA --name BHSA --sse 8000

# Or with Docker Compose
docker compose up client
```

### Available tools (11)

| Category  | Tool                  | Description                                              |
| --------- | --------------------- | -------------------------------------------------------- |
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
from client.mcp import mcp, corpus_manager

corpus_manager.load("~/.exegia/datasets/bibles/BHSA", name="BHSA")
mcp.run(transport="sse", host="localhost", port=8000)
```

---

## Corpus datasets

Datasets are Text-Fabric archives extracted locally under `~/.exegia/datasets/`.

### Fetch from git

```python
from shared.corpus.fetch_from_git import fetch_datasets_from_git

paths = fetch_datasets_from_git("https://github.com/ETCBC/bhsa")
# returns list[Path] of dirs containing otext.tf + otype.tf
```

---

## Importing books (EPUB / HTML)

Books can be converted from EPUB or HTML into Text-Fabric datasets for corpus querying.

```bash
pip install "corpora-admin-py[full]"
```

```python
from admin.utils.convert_epub_to_tf import convert_epub_to_tf

tf_path = convert_epub_to_tf(
    epub_path="commentary.epub",
    output_dir="~/.exegia/datasets/books/my-commentary/",
    corpus_name="MyCommentary",
)
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
uv build --package corpora-shared-py --wheel --out-dir dist/
uv build --package corpora-client-py --wheel --out-dir dist/
uv build --package corpora-admin-py  --wheel --out-dir dist/

# Bump version + publish to PyPI
uv run scripts/publish.py          # bump patch, commit, tag, push
uv run scripts/publish.py minor    # bump minor
uv run scripts/publish.py 1.2.3    # explicit version
```

### Project layout

```
corpora-py/
├── pyproject.toml          # Workspace root + umbrella package (corpora-py)
├── uv.lock
├── packages/
│   ├── shared/             # corpora-shared-py
│   │   └── src/shared/     #   auth, supabase, models, schemas, corpus fetch, epub parse
│   ├── client/             # corpora-client-py
│   │   └── src/client/
│   │       └── mcp/        #   FastMCP server (cf-mcp entrypoint)
│   └── admin/              # corpora-admin-py
│       └── src/admin/
│           └── utils/      #   EPUB/HTML → TF converters ([full] extra)
├── src/
│   └── corpora_py/         # Umbrella module (__version__ only)
├── scripts/
│   ├── setup.py            # Install deps + dotenvx + demo runtime
│   ├── clean.py            # Remove caches and build artifacts
│   ├── publish.py          # Bump version + build + publish helper
│   └── build/              # Sidecar/demo Python bundling scripts
├── Dockerfile.client       # MCP server image (corpora-client-py only)
├── Dockerfile.admin        # Admin/converter image (corpora-admin-py[full])
├── docker-compose.yml
└── .github/
    ├── workflows/
    │   ├── publish.yml       # bump → build → publish to PyPI on PR merge
    │   └── build-sidecar.yml # build + sign platform bundles for Tauri/ElectroBun
    └── actions/
        ├── bump-version/     # Bumps version across all workspace pyproject.toml files
        ├── build-dist/       # Builds all four wheels
        └── publish-pypi/     # Publishes to PyPI via OIDC trusted publishing
```
