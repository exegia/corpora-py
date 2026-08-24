# CLAUDE.md — `admin.services`

HTTP surface over the conversion/validation pipelines (FastAPI routers, WebSocket, job manager)
plus the stored-`.corpus` Hub surfaces. See `packages/admin/CLAUDE.md` for the package overview and
the **"API Work Goes in admin.services"** placement rule; this file covers only what's specific to
`services/`.

Routers here are mounted by the umbrella app (`corpora_py.app`), not self-served. Re-export a new
router from `admin.services/__init__.py`, then import + mount it in `corpora_py.app`.

## Hub storage (`storage*.py`)

`storage.py` wraps `huggingface_hub.HfApi` to list/inspect/upload/download/delete finished `.corpus`
archives in one Hub location (`HF_STORAGE_REPO`; `HF_TOKEN` for auth — both in
`common.utils.config.Settings`). `HF_STORAGE_REPO_TYPE` picks the backend: a **bucket** (Xet object
storage, `hf://buckets/<owner>/<name>/...`, the default — a `.corpus` archive is opaque, not a
browsable dataset) or a classic repo (`model`/`dataset`/`space`). `CorpusStorage` routes every
operation to the matching `huggingface_hub` API (`*_bucket_*` vs `*_repo_*`/`upload_file`) and
presents the same `StoredCorpus` regardless, so both surfaces below are backend-agnostic. An
unconfigured location raises `StorageNotConfiguredError` per call (→ HTTP 503), never at import time. Two surfaces share it: `storage_api.py` (REST `/storage`, job-first uploads with the same job-visibility
404 rule as `/convert/{id}`) and `storage_mcp.py`
(`storage_*` MCP tools). **`storage_mcp.py` imports `fastmcp`, which is not a `corpora-admin`
dependency** — it is deliberately excluded from `admin.services.__init__` and only imported by
`corpora_py.app`, which calls `register_storage_tools(mcp)` before building the MCP ASGI app. Registering the tools
inside `corpora_mcp` instead would force the slim MCP package to depend on admin — don't. All `CorpusStorage` calls are
blocking network I/O; both surfaces must go through
`asyncio.to_thread`.

**Read-only mode (`HF_READ_ONLY`, `common.utils.config`).** When set (a public,
tokenless deployment running `AUTH_REQUIRED=false`), every Hub write is refused so the anonymous public
can browse/query but not mutate the repo. Enforced in three layers, most authoritative first: (1)
`CorpusStorage.upload`/`.delete` raise `ReadOnlyStorageError` — the true chokepoint, since **every** write
path (including the manifest/annotation PATCHes, which re-upload via `corpus_detail._republish`) funnels
through these two methods, so the guard holds for HTTP, MCP, and any future caller by construction; (2) the
`require_writable` FastAPI dependency (defined in `storage_api`, shared by the storage and corpus-detail
write routes) returns **403** up front, before any Hub download, so anonymous callers can't drive billable
Hub I/O — both `_run` mappers also map a leaked `ReadOnlyStorageError` to 403; (3)
`register_storage_tools`/`register_corpus_detail_tools` take a `read_only` kwarg (passed from
`corpora_py.app` as `settings.hf_read_only`) and skip registering the four **write** tools
(`storage_upload_corpus`, `storage_delete_corpus`, `corpus_manifest_update`, `corpus_node_annotate`)
entirely, so they never appear in a public client's tool list. Default `False`, so the desktop sidecar and
local dev stay writable.

**There is deliberately no "public upload" escape hatch.** On the public demo the Hub is read-only, full
stop: an anonymous visitor converts and downloads their own `.corpus`, and nothing they do reaches the Hub.
Publishing stays an owner action, done locally against a writable deployment. If you are tempted to add a
narrow allowance (e.g. "let a visitor publish the job they just converted"), that was considered and
rejected — it makes an unauthenticated deployment a write path to the owner's Hub account, and the demo
gets everything it needs without one.

## Corpus detail (`corpus_detail*.py`)

A *detail* layer over Hub storage for the desktop app's reader: read/patch a stored archive's
`manifest.yml`, list its section structure, and read its text by reference — things flat `/storage`
doesn't give. Same one-implementation/two-surfaces shape as storage:

- **`corpus_detail.py`** — all the logic. `get_manifest`/`update_manifest`/`get_index`/`get_content`. It normalizes the
  filename with `_safe_name` (mirrors `storage._safe_archive_name`), downloads the archive via `CorpusStorage`, extracts
  it with `_safe_extract` (rejects any zip member escaping the target dir), and for index/content loads the Text-Fabric
  payload under `corpora/` with
  `cfabric.Fabric` (imported locally inside `_load_api`, keeping the module import `cfabric`-free). Everything is
  blocking.
- **`corpus_detail_api.py`** — REST router (`prefix="/storage"`): `GET`/`PATCH
  /storage/{filename}/manifest`, `GET /storage/{filename}/index`, `GET /storage/{filename}/content`
  (`ref`/`fmt`/`offset`/`limit` query params). Shares the `/storage/{filename}` path space with
  `storage_api` — the extra segment keeps every route distinct, so router inclusion order is irrelevant. `_run` maps
  errors identically to `storage_api._run`: **503** (storage never configured), **404** (missing archive *or*
  unresolvable section reference), **502** (Hub rejected it). Unlike `/convert` and job-first `/storage` uploads, these
  routes have **no per-resource ownership check** — only the app-wide `AuthMiddleware` gates them.
- **`corpus_detail_mcp.py`** — MCP tools `corpus_manifest_get`, `corpus_manifest_update`,
  `corpus_index`, `corpus_content`, `corpus_node_get`, `corpus_node_annotate`. **Imports `fastmcp`, so — exactly like `storage_mcp` — it is deliberately excluded
  from `admin.services.__init__`** and only imported by `corpora_py.app`, which calls
  `register_corpus_detail_tools(mcp)` alongside `register_storage_tools(mcp)`.
  `corpus_detail_api` (no fastmcp) *is* re-exported from `__init__`. A standalone `cf-mcp` process never registers
  these — it has no Hub storage to read from.

**In-process cache + invalidation.** `corpus_detail._cache` (filename → extracted dir + lazily loaded api, guarded by
`_lock`) keeps a downloaded/extracted archive around so repeated manifest/index/content reads don't re-fetch.
The writers (`update_manifest`, `annotate_node`) share `_republish`: re-zip the extracted archive, re-upload it to the
Hub, then `invalidate(filename)` so the next read re-fetches the updated bytes — **PATCHes are the only writers, and
they always invalidate.** `annotate_node` records node-type corrections in an `annotations.json` sidecar at the archive
root (`{"nodes": {"<id>": {otype, note, converted_otype, updated_at}}}`); the converted Text-Fabric payload under
`corpora/` is never rewritten. `get_node` surfaces one node's otype/slot-span/features/text plus its sidecar entry;
content passages carry their `node` id so clients can cherry-pick nodes without a ref→node round-trip. `corpus_storage`,
`_HUB_CACHE_ROOT`, and `_cache` are module-level so a test can monkeypatch one fake `corpus_storage`
and cover the REST router and MCP tools alike.

**Section-ref fallback gotcha (`_resolve_section_node`).** Turning a human ref (`"Genesis 1"`) back into a TF node tries
`T.nodeFromSection` first (works for language-aware multi-level corpora like BHSA), then **falls back to string-matching
each candidate node's `T.sectionFromNode` ref against the target.** The fallback is not optional here: this repo's
converters emit **single-section-level**
corpora (one root node whose section feature is `title`, carrying no language), so `nodeFromSection`
can't resolve them and only the string match guarantees the index → content round-trip. `_passage_nodes`
similarly special-cases the single-level case (paginate the finest slot-bearing type, not the lone root section). Keep
this in sync with `corpora_mcp.server`'s ref parsing, which it was adapted from.

## Docling ingestion (`ingest_api.py`)

`POST /ingest` is the fire-and-poll sibling of `POST /convert` for the **canonical-graph pipeline**
(`admin.ingest`, see `packages/admin/CLAUDE.md`): upload a document (PDF/DOCX/PPTX/HTML/MD/images —
Docling auto-detects, no `source_format` field), a `JobManager` worker runs Docling + the graph
mapper, and `GET /ingest/{id}/download` serves the schema-validated `graph.json`. It shares
`api.py`'s `_WORK_ROOT`/`_RESULTS_ROOT`/`_save_upload` and the same job-visibility 404 rule, and
503s when the `corpora-admin[docling]` extra isn't installed (checked up front, not mid-job).
`ConversionJob.source_format` is `SourceFormat | str` because ingest jobs record the detected file
suffix (e.g. `"docx"`) — formats the parser enum doesn't enumerate. The shared Docling
`DocumentConverter` is held behind a lock in `admin.ingest.docling_graph` (model warm-up is
expensive; concurrent `convert()` is not documented as safe), so parallel ingest jobs serialize on
the parse step.

## Result filename + Content-Disposition (`jobs.py`, `api.py`, issues #108/#109)

Every job exposes a `result_filename` in `to_dict()` (and therefore on the WebSocket/REST status
push): the human-readable filename a client should store the result under, always ending in
`.corpus` for `/convert` jobs and `.graph.json` for `/ingest` jobs. The stem is
`_slugify(display_name or name)` (lowercased, non-alphanumeric runs collapsed to a single `-`);
an empty/punctuation-only name falls back to the job id. Clients must use this rather than
inventing `${uploadStem}.corpus` — the library contract is that only `.corpus` archives appear in
the list, and the stored name follows the human-readable title, not the upload filename.
`GET /convert/{id}/download`'s `Content-Disposition` echoes `result_path.name` back (with
`media_type=application/zip`, since a `.corpus` archive is a zip — an unknown type makes some
browsers treat the download as raw bytes), so the Save-As default always matches the
`result_filename` the client already received.

The on-disk file in `_RESULTS_ROOT` is named the same way via `_resolve_corpus_path`, with a
short uuid suffix appended on collision (two jobs with the same display name finishing close
together) so concurrent conversions never overwrite each other. `result_filename` tracks that
suffix when `result_path` is set, so a client echoing it back on download matches the actual
archive.

## Display name / title derivation (`jobs.py`, `api.py`, issue #109)

`ConversionJob.display_name` is the human-readable title written to `manifest.name`, derived
in `_run_conversion` **before** the expensive TF walk so it's available on the running status:
`_extract_source_title` calls the format parser's lightweight `parse_metadata` (TEI
`teiHeader`, PDF `info`, HTML `<title>`, EPUB `dc:title` — headers only, not the full parse)
and returns `metadata.title`. The priority is: source title → request `name` →
`_clean_filename_stem` (the upload filename stem with `-`/`_` replaced by spaces). Formats
without a parser (`tf_zip` — already a dataset; `tei_zip` — multiple documents, no single
title) get `None` from `_extract_source_title` and fall back to the request `name`.

`display_name` is `None` while the job is `QUEUED` (the worker hasn't run yet), set via
`JobManager.set_display_name(job_id, ...)` once the worker extracts it, and exposed in
`to_dict()` alongside the original request `name`. The slug-based `result_filename` is derived
from `display_name` once set, so the on-disk archive name follows the human title
(`"Summa Theologiae"` → `summa-theologiae.corpus`), not the upload filename stem
(`summa-theologia-1200-ENG.xml`). Clients should prefer `display_name` for the library display
title and `result_filename` for the stored filename.

## Known gaps (service-side)

**TL;DR:** No real progress reporting during conversion (fixed checkpoints only), no process isolation for hung jobs, no
shared (cross-process) `JobStore` implementation, no TTL reap for the Hub caches. (Converter-side gaps live in
`src/admin/converters/CLAUDE.md`.)

- **`ConversionJob.logs`/`last_log` (`jobs.py`) are fixed checkpoint strings, not real progress.**
  `_run_conversion` (`api.py`) calls
  `job_manager.log()` three times per job (parse start, TF-dataset-built, done) so `/convert/{id}/ws` clients have
  *something* to show besides a status stuck on `"running"` for minutes. `converter()` and
  `convert_to_corpus()` still have no mid-call progress hook — adding real per-unit progress needs threading a callback
  through every
  `_{format}_to_tf.py` converter and `_walker.convert_document()`, not just more log calls here.
- **Tracked-job retention is TTL-reaped; orphaned files and Hub caches are not.** `JobManager` lazily reaps
  terminal jobs older than `JOB_RETENTION_SECONDS` (0 = keep forever, the default) on each `list_jobs`/`submit`,
  deleting the job entry *and* its `result_path` file — so `_RESULTS_ROOT` and the in-memory registry stay bounded
  for jobs the store still knows about. Two gaps remain: (1) with the default `MemoryJobStore`, a restart forgets
  all jobs, orphaning their `_RESULTS_ROOT` files forever (a shared `JobStore` fixes this by construction); (2)
  `_HUB_CACHE_ROOT` (`storage_api.py` — archives fetched from the Hub for `GET /storage/{filename}/download`) still
  has no TTL reap, as does `corpus_detail._HUB_CACHE_ROOT` (and its in-process `_cache`) — the extracted archives it
  caches per filename are only ever dropped by a manifest PATCH's `invalidate()`, never reaped by age.
- **`JobManager`'s stall watchdog (`_check_stall`) cannot actually stop a hung conversion.** It marks a job `FAILED`
  after `stall_timeout_seconds`
  of wall-clock `RUNNING` time so clients stop waiting on it, but a
  `ThreadPoolExecutor` has no way to kill a thread that's already running — the underlying worker thread keeps executing
  the stuck call (e.g. a malformed PDF looping in `pypdf`) indefinitely, permanently occupying one of the pool's
  `max_workers` slots. A real fix needs process-isolated execution (subprocess or `ProcessPoolExecutor`), which in turn
  requires
  `JobManager.submit()` to accept a picklable job spec instead of an arbitrary closure (`api.py` currently passes a
  `lambda` closing over
  `source_path`/`work_dir`/etc., which cannot cross a process boundary).
- **No *shared* job-store implementation ships yet.** `JobManager` now fronts a pluggable `JobStore` (the seam a
  Postgres/Redis-backed impl plugs into, so jobs survive instance recycling and are visible cross-process), but the
  only implementation in-tree is the in-process `MemoryJobStore` — so the service is still effectively
  single-process (see `corpora_py.app.main()`, which hardcodes `workers=1`). Note the *executor* is a separate
  concern a shared store does not solve: running conversions still live in one process's thread pool, so a
  multi-instance deployment with a shared store gets shared *visibility*, not work distribution.
