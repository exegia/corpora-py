# corpora-admin

Admin / conversion tooling for the Corpora platform: turns EPUB, HTML, XML, TEI,
PDF, plain-text and packaged Text-Fabric sources into
[Text-Fabric](https://annotation.github.io/text-fabric/) datasets, compiles those
into [Context-Fabric](https://context-fabric.ai)'s `.cfm` cache, and packages the
result into a `.corpus` archive — the format both the Corpora and Exegia apps
consume. It also owns every HTTP and MCP surface built on top of that pipeline.

`text-fabric` and `context-fabric` are plain dependencies (no `[full]` extra —
installing `corpora-admin` always includes them), which the slim MCP runtime
(`corpora-mcp`) doesn't need. The one extra is `[docling]`, for `/ingest`.

> **Installed as part of `corpora-py`.** Only the umbrella distribution is
> published to PyPI; its wheel bundles this package's source. Use
> `pip install corpora-py` and `import admin`, or add this package to a uv
> workspace for local development.

## Pipeline

```
source document  --parse-->  Document/Unit tree  --walk-->  Text-Fabric (.tf)  --compile-->  .cfm cache  --package-->  .corpus
     (admin.parsers)              (shared schema)          (admin.converters)      (cfabric)              (admin.converters)
```

1. **Parse** — a format-specific `Parser` (`admin.parsers`) reads a source
   file/URL into one shared, format-agnostic tree: `Document` (metadata) +
   nested `Unit`s (chapters, pages, paragraphs, … down to `Token`s).
2. **Convert to Text-Fabric** — a `_{format}_to_tf.py` converter
   (`admin.converters`) walks that tree into a Text-Fabric dataset via the
   shared `_walker.py` (`tf.convert.walker.CV`), declaring its hierarchy as a
   `SectionSpec` and returning a `ConvertedDataset`.
3. **Compile to Context-Fabric** — `convert_to_cfm()` loads the `.tf` dataset
   through `cfabric.Fabric(...).loadAll()`, producing the memory-mapped `.cfm`
   cache Context-Fabric reads at runtime.
4. **Package** — `convert_to_corpus()` bundles the `.tf`/`.cfm` payload with a
   `manifest.yml`, `toc.yml`, optional cover/asset images, and a git repository
   for version history, into a single `.corpus` zip. See the schema doc
   referenced in `converters/convert_to_corpus.py` for the archive contract, and
   [Corpus validation & .cfm integrity checking](../../docs/lessons/corpus-validation-and-cfm-integrity.md)
   for how the packaged cache is validated.

A second, independent pipeline lives in `admin.ingest`: Docling → the
**Context Fabric v1 canonical graph** (`graph.json`, schema-validated against
`common.schemas.context_fabric.v1`). It does not produce Text-Fabric, and is
exposed separately at `/ingest`.

## Supported formats

| Format | Parser | Converter | Notes |
|---|---|---|---|
| EPUB | `EpubParser` | `convert_epub_to_tf` | One `chapter` node per spine document |
| HTML | `HtmlParser` | `convert_html_to_tf` | One `document` node wrapping every top-level element |
| XML | `XmlParser` | `convert_xml_to_tf` | Generic element tree → `section`/`paragraph` nesting |
| TEI | `TeiParser` | `convert_tei_to_tf` | One node per top-level `<div>`; `<head>` → `label` |
| TEI (zip) | `TeiParser` | `convert_tei_zip_to_tf` | Multi-file TEI editions in one archive |
| PDF | `PdfParser` | `convert_pdf_to_tf` | One `page` node per PDF page |
| Plain text | `PlainTextParser` | `convert_text_to_tf` | One `paragraph` node per blank-line-separated block |
| Text-Fabric zip | — | `convert_tf_zip_to_tf` | Re-package an existing `.tf` dataset; no parse step |

`_category.py` classifies the result (`document` / `book` / `religious`) into
`manifest.category`, so a chapterless PDF and a book/chapter/verse Bible are
presented differently downstream.

## Install

```bash
# From the workspace root (editable, all packages)
uv sync

# Just this package, editable
uv sync --package corpora-admin

# Published distribution (bundles this package's source)
pip install corpora-py
pip install 'corpora-py[docling]'   # adds the full Docling converter for /ingest
```

## Usage

```python
from admin.parsers import PdfParser, SourceFormat
from admin.converters import CONVERTERS, convert_to_corpus

# Parse only (inspect the Document/Unit tree without touching Text-Fabric)
document = PdfParser().parse("book.pdf")

# Full pipeline: source -> .tf -> .corpus
tf_dir = CONVERTERS[SourceFormat.PDF]("book.pdf", "out/book.tf")
corpus_path = convert_to_corpus(
    tf_dir,
    "out/book.corpus",
    name="My Book",
    description="Converted from a scanned PDF",
    language="English",
    language_code="en",
)
```

Transport-free conversion (the same work `/convert` does in a job thread) is
`admin.services.conversion.run_conversion` — that's what the standalone
[`corpora` CLI](https://github.com/exegia/corpora-cli) calls.

## HTTP and MCP surfaces

Every router here is a plain `APIRouter` meant to be included into the combined
app in `src/corpora_py/app.py`; this package never builds its own `FastAPI`
instance.

| Module | Routes | MCP twin |
|---|---|---|
| `api.py` | `POST/GET /convert`, `GET /convert/{id}`, `/download`, plus the job-scoped detail layer (`/manifest`, `/index`, `/sections`, `/content`, `/nodes/{n}`, `/versions`, `/diff`, `/restore`) | — |
| `websocket.py` | `/convert/{id}/ws` (status push) | — |
| `corpus_detail_api.py` | `/storage/{filename}/{manifest,index,sections,content,nodes/{n},versions,restore}` over published archives | `corpus_*` |
| `storage_api.py` | `GET/POST /storage`, `GET/DELETE /storage/{filename}`, `/download` | `storage_*` |
| `reference_api.py` | `POST /refs`, `GET /refs/resolve`, `GET/POST /refs/shortcode` | `corpus_reference_*` |
| `validation_api.py` | `POST /validate` | `validate_corpus` (in `corpora-mcp`) |
| `ingest_api.py` | `POST/GET /ingest`, `/download` | — |

`storage_mcp` / `corpus_detail_mcp` / `reference_mcp` are deliberately **not**
imported from `admin.services.__init__`: they import `fastmcp`, which is a
dependency of `corpora-mcp` and the umbrella app, not of `corpora-admin`. Eagerly
importing them would break a slim admin-only `import admin`. The umbrella app
imports them explicitly and registers the tools onto the shared server.

**Read-only mode.** `CorpusStorage.upload`/`.delete` raise `ReadOnlyStorageError`
when `HF_READ_ONLY=true`, and every write funnels through them (manifest and
annotation PATCHes re-upload via `_republish`), so writes are blocked by
construction. `storage_api`'s `require_writable` dependency short-circuits with
**403** before any Hub I/O, and the four write MCP tools aren't registered at
all. See [`src/admin/services/CLAUDE.md`](src/admin/services/CLAUDE.md).

## Module map

- **`admin.parsers`** — `schema.py` defines the shared `Document`/`Unit`/`Token`
  schema, the `SourceFormat` enum and the `Parser` ABC every format implements.
  Each `_{format}.py` is one parser; `PARSERS` maps `SourceFormat` → instance.
- **`admin.converters`** — `_walker.py` holds the shared Text-Fabric walk (every
  parser reduces to the same tree, so it's written once); each
  `_{format}_to_tf.py` supplies only the format-specific choices (root node name,
  `Unit.type` → TF node type, `SectionSpec`). `convert_to_cfm.py` and
  `convert_to_corpus.py` are the packaging stages; `_category.py` classifies.
- **`admin.ingest`** — Docling → Context Fabric v1 graph (`docling_graph.py`),
  deterministic id minting (`_ids.py`), schema validation (`validation.py`).
- **`admin.services`** — the surfaces above, plus `jobs.py` (`JobManager`, a
  `ThreadPoolExecutor` over a pluggable `JobStore` — `job_store_supabase.py` is
  the shared implementation selected by `JOB_STORE=supabase`), `storage.py`
  (Hugging Face Hub, with `storage_supabase.py` as the owner-scoped alternative
  selected by `STORAGE_BACKEND`), `conversion.py` (transport-free pipeline
  entry point) and `upload_validation.py` (pre-conversion upload checks).

## Development

```bash
# From the workspace root
uv run ruff check packages/admin/
uv run mypy packages/admin/src --ignore-missing-imports
uv run pytest tests/admin
uv build --package corpora-admin --wheel --out-dir dist/
```
