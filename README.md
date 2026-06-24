# Exegia Backend

> Graph-based biblical and religious text study API — powered by Context-Fabric, FastAPI, Strawberry GraphQL, and FastMCP.

---

## What is this?

Exegia is a backend for studying annotated religious texts (Bible, Quran, Tanakh, commentaries, lexicons). It exposes corpus data through two surfaces:

| Surface         | Technology           | Use case                          |
| --------------- | -------------------- | --------------------------------- |
| **GraphQL API** | Strawberry + FastAPI | Frontend apps, structured queries |
| **MCP server**  | FastMCP              | AI assistants (Claude, GPT, etc.) |

Corpora are loaded from [Context-Fabric](https://context-fabric.ai) — a graph-based annotated text engine. Every word, verse, chapter, and book is a typed node in a graph with queryable features (lemma, morphology, gloss, etc.).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Clients                             │
│       Frontend     │   AI Assistant    │   CLI / Script     │
└────────┬───────────┴────────┬──────────┴────────┬───────────┘
         │                    │                   │
   GraphQL (Strawberry)  MCP (FastMCP)      REST (FastAPI)
         │                    │                   │
┌────────▼────────────────────▼───────────────────▼───────────┐
│                       exegia package                        │
│    .graphql   │   .mcp   │   .corpus   │   .utils          │
└───────────────────────────┬─────────────────────────────────┘
                            │
           ┌────────────────▼────────────────┐
           │      Context-Fabric (cfabric)    │
           │   F · E · L · T · S · N · C     │
           └────────────────┬────────────────┘
                            │
           ┌────────────────▼────────────────┐
           │         corpus datasets          │
           │   ~/.exegia/datasets/...         │
           └─────────────────────────────────┘
```

---

## Package modules

Everything lives in the `exegia` namespace (`src/exegia/`):

| Module           | Purpose                                         |
| ---------------- | ----------------------------------------------- |
| `exegia.mcp`     | FastMCP server — 11 corpus tools for AI clients |
| `exegia.graphql` | Strawberry GraphQL schema over corpus data      |
| `exegia.corpus`  | Fetch TF datasets from git repositories         |
| `exegia.utils`   | EPUB / HTML → Text-Fabric converters            |
| `exegia.models`  | Shared enums and data model definitions         |
| `exegia.schemas` | Pydantic request/response schemas               |
| `exegia.auth`    | Auth utilities                                  |

---

## Tech stack

- **Python 3.13+** with [uv](https://docs.astral.sh/uv/) for dependency management
- **FastAPI** — HTTP framework
- **Strawberry GraphQL** — schema-first GraphQL with full type safety
- **FastMCP 2** — MCP server for AI clients
- **Context-Fabric** (`cfabric`) — graph corpus engine (fork of Text-Fabric)

---

## Getting started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) ≥ 0.9
- Python 3.13

### Install

```bash
git clone <repo-url>
cd backend
uv run scripts/setup.py
```

### Environment

```bash
cp .env.example .env
# fill in any required environment variables
```

### Run the API

```bash
uv run uvicorn main:app --reload
```

---

## GraphQL API

The schema exposes a corpus hierarchy: `Corpus → Book → Chapter → Verse → Word`.

**Endpoint:** `POST /graphql`

### Example queries

```graphql
# Fetch a passage
query {
  passage(corpus: "BHSA", reference: "Genesis 1:1-3") {
    reference
    text
    words {
      text
      lemma
      partOfSpeech
      gloss
    }
  }
}

# Morphological word search
query {
  words(corpus: "BHSA", filter: { book: "Genesis", partOfSpeech: "verb", verbTense: "perfect" }, limit: 50) {
    text
    lemma
    gloss
  }
}

# Raw Context-Fabric pattern search
query {
  search(corpus: "BHSA", pattern: "word pos=verb\n  book name=Genesis") {
    reference
    text
  }
}
```

### GraphQL types

| Type          | Key fields                                                                                                        |
| ------------- | ----------------------------------------------------------------------------------------------------------------- |
| `Corpus`      | `name`, `nodeTypes`, `featureCount`, `books`                                                                      |
| `Book`        | `name`, `chapters`                                                                                               |
| `Chapter`     | `reference`, `verses`                                                                                            |
| `Verse`       | `reference`, `text`, `words`                                                                                     |
| `Word`        | `text`, `lemma`, `partOfSpeech`, `gloss`, `gender`, `number`, `person`, `verbStem`, `verbTense`, `feature(name)` |
| `SearchMatch` | `reference`, `text`                                                                                              |

Field names use natural language (`lemma`, `partOfSpeech`) instead of raw corpus shorthand (`lex`, `sp`). Use the `feature(name)` escape hatch to access any raw feature directly.

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
from exegia.mcp import mcp, corpus_manager

corpus_manager.load("~/.exegia/datasets/bibles/BHSA", name="BHSA")
mcp.run(transport="sse", host="localhost", port=8000)
```

---

## Corpus datasets

Datasets are Text-Fabric archives extracted locally under `~/.exegia/datasets/`.

### Fetch from git

```python
from exegia.corpus.fetch_from_git import fetch_datasets_from_git

paths = fetch_datasets_from_git("https://github.com/ETCBC/bhsa")
# returns list[Path] of dirs containing otext.tf + otype.tf
```

---

## Importing books (EPUB / HTML)

Books can be converted from EPUB or HTML into Text-Fabric datasets for corpus querying.

```python
from exegia.utils.convert_epub_to_tf import convert_epub_to_tf

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

The output directory is a valid TF dataset, loadable by the MCP server or GraphQL API immediately:

```bash
uv run cf-mcp --corpus ~/.exegia/datasets/books/my-commentary
```

---

## Development

### Run tests

```bash
uv run pytest
```

### Build the wheel

```bash
uv build --out-dir dist/
```

### Publish

```bash
uv run scripts/publish.py          # bump patch, commit, tag, push
uv run scripts/publish.py minor    # bump minor
uv run scripts/publish.py 1.2.3    # explicit version
```

### Project layout

```
backend/
├── pyproject.toml       # Package config (hatchling build)
├── uv.lock
├── scripts/
│   ├── setup.py         # Install deps + dotenvx
│   ├── clean.py         # Remove caches and build artifacts
│   ├── stop.py          # Stop local uvicorn processes
│   ├── publish.py       # Build + publish helper
│   └── work.py          # Git workflow helper
├── .github/
│   └── workflows/
│       └── publish.yml  # CI: build + publish on tag push
└── src/
    └── exegia/
        ├── auth/        # Auth utilities
        ├── corpus/      # Git dataset fetching
        ├── graphql/     # Strawberry GraphQL schema
        ├── mcp/         # FastMCP server (cf-mcp entrypoint)
        ├── models/      # Enums and data model definitions
        ├── schemas/     # Pydantic API schemas
        └── utils/       # EPUB/HTML → TF converters
```
