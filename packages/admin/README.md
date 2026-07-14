# corpora-admin

Admin / conversion tooling for the Corpora platform: turns EPUB, HTML, XML, TEI, PDF, and plain-text source documents
into
[Text-Fabric](https://annotation.github.io/text-fabric/) datasets, compiles those
into [Context-Fabric](https://context-fabric.ai)'s `.cfm` cache, and packages the result into a `.corpus` archive — the
format both the Corpora and Exegia apps consume.

This package pulls in `text-fabric` and `context-fabric` as plain dependencies (there is no `[full]` extra — installing
`corpora-admin` always includes them), which the slim MCP runtime (`corpora-mcp`) doesn't need.
`admin.services` also exposes this pipeline over HTTP (`POST/GET /convert`, mounted into the combined app at
`src/corpora_py/app.py`) — see "Module map"
below.

## Pipeline

```
source document  --parse-->  Document/Unit tree  --walk-->  Text-Fabric (.tf)  --compile-->  .cfm cache  --package-->  .corpus
     (admin.parsers)              (shared schema)          (admin.converters)      (cfabric)              (admin.converters)
```

1. **Parse** — a format-specific `Parser` (`admin.parsers`) reads a source file/URL into one shared, format-agnostic
   tree: `Document` (metadata) + nested `Unit`s (chapters, pages, paragraphs, ... down to `Token`s).
2. **Convert to Text-Fabric** — a format-specific `_{format}_to_tf.py`
   converter (`admin.converters`) walks that same tree into a Text-Fabric dataset (`tf.convert.walker.CV`).
3. **Compile to Context-Fabric** — `convert_to_cfm()` loads the `.tf` dataset via `cfabric.Fabric(...).loadAll()`, which
   compiles it into the memory-mapped `.cfm` cache Context-Fabric reads at runtime.
4. **Package** — `convert_to_corpus()` bundles the `.tf`/`.cfm` payload with a `manifest.yml`, `toc.yml`, optional
   cover/asset images, and a git repository for version history, into a single `.corpus` zip archive. See the schema doc
   referenced in `converters/convert_to_corpus.py` for the full archive contract, and
   [Corpus validation & .cfm integrity checking](../../docs/lessons/corpus-validation-and-cfm-integrity.md) for how the
   packaged `.cfm` cache is validated.

## Supported formats

| Format     | Parser            | Converter            | Notes                                                |
|------------|-------------------|----------------------|------------------------------------------------------|
| EPUB       | `EpubParser`      | `convert_epub_to_tf` | One `chapter` node per spine document                |
| HTML       | `HtmlParser`      | `convert_html_to_tf` | One `document` node wrapping every top-level element |
| TEI        | `TeiParser`       | `convert_tei_to_tf`  | One node per top-level `<div>`; `<head>` → `label`   |
| PDF        | `PdfParser`       | `convert_pdf_to_tf`  | One `page` node per PDF page                         |
| Plain text | `PlainTextParser` | `convert_text_to_tf` | One `paragraph` node per blank-line-separated block  |
| XML        | `XmlParser`       | *(none yet)*         | Generic tree walk; no TF converter wired up yet      |

## Install

```bash
# From the workspace root
uv sync --package corpora-admin

# Standalone
pip install corpora-admin
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

## Module map

- **`admin.parsers`** — `schema.py` defines the shared `Document`/`Unit`/
  `Token` schema and the `Parser` ABC every format implements. Each
  `_{format}.py` module is one parser; `PARSERS` in `__init__.py` maps
  `SourceFormat` → parser instance.
- **`admin.converters`** — `_walker.py` holds the shared Text-Fabric walking logic (every parser reduces to the same
  tree, so the walk is written once). Each `_{format}_to_tf.py` supplies the handful of format-specific choices (root
  node name, `Unit.type` → TF node type mapping). `convert_to_cfm.py`
  and `convert_to_corpus.py` are the two packaging stages after conversion.
- **`admin.services`** — HTTP surface over the pipeline above: `api.py`
  (`POST /convert` upload + background job, `GET /convert/{id}` poll,
  `GET /convert/{id}/download`), `websocket.py` (`/convert/{id}/ws` status push), `jobs.py` (the in-process `JobManager`
  backing both). Not a standalone app — meant to be included into a FastAPI app (see
  `src/corpora_py/app.py`).

## Development

```bash
# From the workspace root
uv run ruff check packages/admin/
uv run mypy packages/admin/src --ignore-missing-imports
uv build --package corpora-admin --wheel --out-dir dist/
```
