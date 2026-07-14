# CLAUDE.md

This file provides guidance to Claude Code when working in `packages/admin/`
(the `corpora-admin` package). See the workspace root `CLAUDE.md` for the
overall repo; this file only covers what's specific to this package.

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
    converters/               # Document/Unit tree -> Text-Fabric -> .cfm -> .corpus
      _walker.py                # shared TF-walking logic (read this second)
      _epub_to_tf.py, _html_to_tf.py, _tei_to_tf.py, _pdf_to_tf.py, _text_to_tf.py
      convert_to_cfm.py         # .tf -> .cfm (Context-Fabric compile)
      convert_to_corpus.py      # .tf + .cfm -> .corpus archive
      __init__.py               # CONVERTERS: dict[SourceFormat, converter fn]
    services/                 # HTTP surface over the pipeline above (FastAPI routers)
      api.py                    # POST/GET /convert (upload, poll, download)
      websocket.py              # /convert/{id}/ws (status push)
      validation_api.py         # POST /validate (corpus integrity checks)
      jobs.py                   # JobManager (in-process ThreadPoolExecutor job registry)
```

This mirrors `packages/common/src/common/` and `packages/mcp/src/corpora_mcp/`
— every workspace package lives at `packages/{name}/src/{name}/` (mcp's
importable module is `corpora_mcp`, not `mcp`, to avoid colliding with the
real `mcp` SDK — see the root `CLAUDE.md`). **Do not**
move code back to `packages/admin/{parsers,converters}/` (flat, no `src/`) —
that layout was tried twice and both times produced a wheel with zero
code in it (hatchling silently resolves `packages = ["admin"]` or
`packages = ["."]` against the wrong base path or pollutes the wheel with
non-code files). The `src/admin` layout is the one that's been verified to
actually build and import correctly.

## API Work Goes in admin.services

All FastAPI routers for the conversion and validation pipelines live in `admin.services/` and are mounted by the
umbrella app (`corpora_py.app`). This keeps the split clean:
- **`admin`** — owns all API surfaces over its pipelines (conversion, validation)
- **`corpora_py`** (umbrella) — orchestrates: mounts routers, handles auth middleware, combines lifespans

Do not add new HTTP routers to `src/corpora_py/` — add them to `admin.services/` and re-export from
`admin.services/__init__.py`, then import into `corpora_py.app` and mount them. This preserves the invariant that
the umbrella package has zero business logic and exists only to glue the other three together.

## Architecture

**One shared schema, one shared walker.** Every format parser
(`admin.parsers`) reduces its source to the exact same tree —
`Document` (metadata) + recursive `Unit` (a `type` string, `attrs`,
`tokens`, and nested `children`) — instead of six different per-format
schemas. That's what makes `admin.converters._walker.convert_document()`
possible: it's one Text-Fabric walk, written once, reused by every
`_{format}_to_tf.py`. When adding a new format, don't invent a new node
shape — reduce it to `Unit`/`Token` and the rest is free.

**`Unit.type` is a free string, not an enum**, because each source format
has its own vocabulary (`"p"`, `"chapter"`, `"div"`, `"page"`) and new types
must be addable without touching the schema. Each converter's `otype_for()`
callback decides how much of that vocabulary survives into Text-Fabric node
types (e.g. HTML collapses everything to a generic `"element"`; EPUB keeps
`"paragraph"`/`"link"`/`"chapter"` distinct) — see each `_{format}_to_tf.py`
module's docstring for its documented Node Types/Features contract before
changing what it emits; those contracts are what downstream consumers query
against.

### Text-Fabric walker gotchas (all handled in `_walker.py` — read it before
### touching feature/node creation logic)

- **Every feature name must have metadata**, or `cv.walk()` fails validation
  with `"node feature has no metadata"`. Feature names here vary per
  document (HTML attributes, TEI `@type`, ...) so they can't be declared
  upfront in `featureMeta=`; `set_features()` registers each one dynamically
  via `cv.meta(name, valueType="str")` right before setting it. If you add a
  `cv.feature()` call anywhere, route it through `set_features()`, not
  `cv.feature()` directly, or you'll reintroduce this failure.
- **Dynamically-registered features need an explicit `valueType`** or the
  exporter warns `"Missing @valueType"` (non-fatal, but avoidable — that's
  why `set_features()` always passes `valueType="str"`).
- **A node covering zero slots gets silently deleted** by Text-Fabric's
  "remove unlinked nodes" pass. A leaf `Unit` with no tokens and no children
  (a blank PDF page, an `<img>`, an `<hr>`) would otherwise vanish along
  with its attributes — `_walk_unit()` gives genuinely empty leaves one
  placeholder empty-text slot so they survive.
- **`otext.sectionTypes`/`sectionFeatures` can't be empty**, but also don't
  need to be elaborate: every converter uses a single section level (the
  root `book`/`document`/`text` node, with `title` as its section feature).
  Finer structure (chapters, pages, divs) is still expressed as ordinary
  node types via `otype_for` — it just isn't declared as TF "sections",
  which would require strict, consistent nesting we can't guarantee across
  arbitrary source documents.
- **`SKIP_TAGS` in `parsers/_html.py` is scoped to tags that only make sense
  to drop when nested inside `<body>`** (script/style/noscript/svg/math).
  It used to include `"head"` for HTML's metadata tag, which silently ate
  TEI's `<head>` (a heading element, reused by the shared walker) — don't
  add HTML-specific tag names back to that set without checking what they
  mean in TEI/XML first.

## Context-Fabric (`cfabric`) notes

- There is **no separate compile API**. `.cfm` compilation happens
  automatically the first time a dataset is loaded via
  `cfabric.Fabric(locations=...).loadAll()`. `convert_to_cfm()` exists only
  to trigger that load on purpose and hand back the resulting `.cfm` path.
- `Fabric(...).loadAll()` returns `Api | bool` (`False` on failure) — always
  narrow with `isinstance(result, bool)` before touching `.F`/`.T`/`.Fall()`;
  those are dynamically populated at load time so mypy can't see their
  attributes either (hence the `type: ignore[attr-defined]` in
  `convert_to_corpus.py`).

## `.corpus` archive

The archive format (`manifest.yml`, `toc.yml`, `assets/`, `.git/`,
`corpora/{*.tf, .cfm/}`) is the contract both the Corpora and Exegia apps
parse. The canonical spec is maintained in an external vault by the Corpora
team. Before changing manifest/toc shape in `convert_to_corpus.py`, consult
the current schema definition with the team or check the app's schema loader
to understand the expected format.

## Known gaps

**TL;DR:** No real progress reporting during conversion (fixed checkpoints only), no process isolation for hung jobs, no cross-process job registry, no archive cleanup, no test coverage for HTTP API.

- **`ConversionJob.logs`/`last_log` (`services/jobs.py`) are fixed checkpoint
  strings, not real progress.** `_run_conversion` (`services/api.py`) calls
  `job_manager.log()` three times per job (parse start, TF-dataset-built,
  done) so `/convert/{id}/ws` clients have *something* to show besides a
  status stuck on `"running"` for minutes. `converter()` and
  `convert_to_corpus()` still have no mid-call progress hook — adding real
  per-unit progress needs threading a callback through every
  `_{format}_to_tf.py` converter and `_walker.convert_document()`, not just
  more log calls here.
- **No `_xml_to_tf.py`.** `XmlParser` exists (`admin.parsers`) but there's no
  matching Text-Fabric converter — generic XML has no fixed node-type
  vocabulary to map onto, unlike TEI's `<div>`/`<p>` convention. Add one the
  same way as the others (pick an `otype_for`, wire it into
  `converters/__init__.py`'s `CONVERTERS`) if a concrete need shows up;
  don't add it speculatively.
- `dataset_id`/`project_id`/`publisher_id`/`author_ids` in
  `convert_to_corpus()` are caller-supplied and default to `""` — this
  package has no way to know them; they're assigned by whatever backend
  calls it (the Corpora/Exegia app, not this converter).
- **`services/` (the `/convert` HTTP API) has no test coverage.** A
  deliberate scope cut, not an oversight — see the root `CLAUDE.md`'s CI/CD
  section for context. Test strategy (mocking `cfabric`, exercising
  `JobManager` without real conversions) needs its own design pass.
  (Auth *is* covered now — see `corpora_py.auth` and the root `CLAUDE.md`.)
- **`_RESULTS_ROOT` (finished `.corpus` archives, in `services/api.py`) is
  never cleaned up.** `_WORK_ROOT` (uploads + intermediate Text-Fabric
  output) *is* deleted once a job reaches a terminal state, but there's no
  "client downloaded it, safe to delete" signal for the final archive, and a
  naive delete-on-download would break retries. Needs a TTL-based reap (a
  periodic task deleting files older than N hours) — not implemented yet.
  `JobManager._jobs` has the same problem: terminal job entries are never
  pruned from the in-memory registry, so it grows for the lifetime of the
  process.
- **`JobManager`'s stall watchdog (`_check_stall`) cannot actually stop a
  hung conversion.** It marks a job `FAILED` after `stall_timeout_seconds`
  of wall-clock `RUNNING` time so clients stop waiting on it, but a
  `ThreadPoolExecutor` has no way to kill a thread that's already running —
  the underlying worker thread keeps executing the stuck call (e.g. a
  malformed PDF looping in `pypdf`) indefinitely, permanently occupying one
  of the pool's `max_workers` slots. A real fix needs process-isolated
  execution (subprocess or `ProcessPoolExecutor`), which in turn requires
  `JobManager.submit()` to accept a picklable job spec instead of an
  arbitrary closure (`api.py` currently passes a `lambda` closing over
  `source_path`/`work_dir`/etc., which cannot cross a process boundary).
- **No cross-process job registry.** `JobManager` is an in-memory,
  per-process singleton (see its class docstring and `corpora_py.app.main()`,
  which hardcodes `workers=1` specifically because of this). Scaling this
  service beyond one process needs a shared backend (Redis, Celery, or
  similar) instead of — or in front of — `JobManager`.
