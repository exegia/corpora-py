# CLAUDE.md

This file provides guidance to Claude Code when working in `packages/admin/`
(the `corpora-admin` package). See the workspace root `CLAUDE.md` for the overall repo; this file only covers what's
specific to this package.

Two subsystems have their own directory-scoped guides (auto-loaded when you work in them):

- **`src/admin/services/CLAUDE.md`** — the `/convert`, `/validate`, and `/storage` HTTP surfaces, Hub storage, corpus
  detail, the `JobManager`, and their known gaps.
- **`src/admin/converters/CLAUDE.md`** — the Text-Fabric walker gotchas, Context-Fabric (`cfabric`) notes, the `.corpus`
  archive contract, and converter-side gaps.

## Commands

```bash
# Run from the workspace root, not from packages/admin/

# Install / re-sync this package's deps
uv sync --package corpora-admin

# Lint / type-check
uv run ruff check packages/admin/
uv run mypy packages/admin/src --ignore-missing-imports

# Build the wheel and actually inspect its contents — `uv sync` alone will
# NOT catch a broken `[tool.hatch.build.targets.wheel] packages` path; it
# happily installs an empty editable package with no error. Always verify
# with a real build after touching pyproject.toml:
uv build --package corpora-admin --wheel --out-dir /tmp/wheelcheck
python -m zipfile -l /tmp/wheelcheck/*.whl   # should list admin/parsers/*.py, admin/converters/*.py
```

## Layout

```
packages/admin/
  pyproject.toml           # packages = ["src/admin"] — must match this path exactly
  src/admin/
    __init__.py             # from . import converters, parsers, services
    parsers/                 # source document -> Document/Unit tree
      schema.py               # the shared schema + Parser ABC (read this first)
      _epub.py, _html.py, _xml.py, _tei.py, _pdf.py, _plain.py
      __init__.py              # PARSERS: dict[SourceFormat, Parser]
    converters/               # Document/Unit tree -> Text-Fabric -> .cfm -> .corpus  (see converters/CLAUDE.md)
      _walker.py                # shared TF-walking logic (read this second)
      _epub_to_tf.py, _html_to_tf.py, _tei_to_tf.py, _pdf_to_tf.py, _text_to_tf.py
      convert_to_cfm.py         # .tf -> .cfm (Context-Fabric compile)
      convert_to_corpus.py      # .tf + .cfm -> .corpus archive
      __init__.py               # CONVERTERS: dict[SourceFormat, converter fn]
    services/                 # HTTP surface over the pipeline above (FastAPI routers)  (see services/CLAUDE.md)
      api.py                    # POST/GET /convert (upload, poll, download)
      websocket.py              # /convert/{id}/ws (status push)
      validation_api.py         # POST /validate (corpus integrity checks)
      storage.py                # CorpusStorage: .corpus archives on the Hugging Face Hub
      storage_api.py            # /storage REST surface over storage.py
      storage_mcp.py            # storage_* MCP tools (registered by corpora_py.app, NOT here)
      corpus_detail.py          # read/patch manifest, section index, paginated content of a stored archive
      corpus_detail_api.py      # /storage/{filename}/{manifest,index,content} REST surface
      corpus_detail_mcp.py      # corpus_* MCP tools (registered by corpora_py.app, NOT here)
      jobs.py                   # JobManager (in-process ThreadPoolExecutor job registry)
```

This mirrors `packages/common/src/common/` and `packages/mcp/src/corpora_mcp/`
— every workspace package lives at `packages/{name}/src/{name}/` (mcp's importable module is `corpora_mcp`, not `mcp`,
to avoid colliding with the real `mcp` SDK — see the root `CLAUDE.md`). **Do not**
move code back to `packages/admin/{parsers,converters}/` (flat, no `src/`) — that layout was tried twice and both times
produced a wheel with zero code in it (hatchling silently resolves `packages = ["admin"]` or
`packages = ["."]` against the wrong base path or pollutes the wheel with non-code files). The `src/admin` layout is the
one that's been verified to actually build and import correctly.

## API Work Goes in admin.services

All FastAPI routers for the conversion and validation pipelines live in `admin.services/` and are mounted by the
umbrella app (`corpora_py.app`). This keeps the split clean:

- **`admin`** — owns all API surfaces over its pipelines (conversion, validation)
- **`corpora_py`** (umbrella) — orchestrates: mounts routers, handles auth middleware, combines lifespans

Do not add new HTTP routers to `src/corpora_py/` — add them to `admin.services/` and re-export from
`admin.services/__init__.py`, then import into `corpora_py.app` and mount them. This preserves the invariant that the
umbrella package has zero business logic and exists only to glue the other three together.

See **`src/admin/services/CLAUDE.md`** for the details of each surface (Hub storage, corpus detail, the `fastmcp`
exclusion rule, and the service-side known gaps).

## Architecture

**One shared schema, one shared walker.** Every format parser (`admin.parsers`) reduces its source to the exact same
tree —
`Document` (metadata) + recursive `Unit` (a `type` string, `attrs`,
`tokens`, and nested `children`) — instead of six different per-format schemas. That's what makes
`admin.converters._walker.convert_document()`
possible: it's one Text-Fabric walk, written once, reused by every
`_{format}_to_tf.py`. When adding a new format, don't invent a new node shape — reduce it to `Unit`/`Token` and the rest
is free.

**`Unit.type` is a free string, not an enum**, because each source format has its own vocabulary (`"p"`, `"chapter"`,
`"div"`, `"page"`) and new types must be addable without touching the schema. Each converter's `otype_for()`
callback decides how much of that vocabulary survives into Text-Fabric node types (e.g. HTML collapses everything to a
generic `"element"`; EPUB keeps
`"paragraph"`/`"link"`/`"chapter"` distinct) — see each `_{format}_to_tf.py`
module's docstring for its documented Node Types/Features contract before changing what it emits; those contracts are
what downstream consumers query against.

The Text-Fabric / Context-Fabric mechanics of that walk, and the `.corpus` archive it produces, are documented in
**`src/admin/converters/CLAUDE.md`**.
