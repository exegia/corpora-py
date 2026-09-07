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

## Library storage split: Supabase owns the library, the Hub is for publishing (issue #110)

A product frontend's **library** (each user's own converted corpora — what corpora-web shows in
Reader / Structure / Analytics) is **not** backed by `/storage`. The contract is:

- **Conversion result → client downloads → client stores it.** After `GET /convert/{id}/download`,
  the client owns persistence: corpora-web uploads the `.corpus` to its private Supabase bucket
  (`project-corpora`) and records the path in its own `corpus_documents` table. This service never
  `POST /storage`s a library corpus on the user's behalf, and never talks to Supabase Storage at all
  (Supabase appears in this repo only as a JWT issuer — see the root `CLAUDE.md`'s Auth section).
- **Explore reads come from the job, not the Hub.** The job-scoped detail endpoints
  (`GET /convert/{job_id}/{manifest,index,sections,content,nodes/{node},versions,diff}`, see
  `api.py`) serve the same response shapes as `/storage/{filename}/…` from the job's result
  archive — no Hub download, no filename matching. With the default in-memory store that
  archive is the converting instance's on-disk `result_path`; with `JOB_STORE=supabase`
  (issue #140) it is materialized from the shared result bucket, so reload after instance
  recycle still works. The stable client-side key is the `job_id`.
- **`/storage` (Hugging Face Hub) is the *publishing* surface only** — an owner action to share a
  corpus publicly, done against a writable deployment. On the public demo (`HF_READ_ONLY=true`) the
  Hub is read-only and library conversions are unaffected: nothing in the convert → download →
  explore path touches the Hub, so no conversion is ever blocked on a Hub 403.

Do **not** "fix" an empty library view by matching library rows against `GET /storage` filenames —
the Hub holds unrelated public archives and the library never lives there. If job-scoped reads are
insufficient (e.g. after the instance recycled and the job's `result_path` is gone), the sanctioned
extension is a second `CorpusStorage`-style backend or a shared `JobStore` — a deliberate
architecture decision, not a quiet workaround (issue #110 options B/C).

### Option C ships: the Supabase Storage backend (`storage_supabase.py`, issue #129)

`STORAGE_BACKEND=supabase` (default `huggingface`) makes `storage.make_corpus_storage()` build a
`SupabaseCorpusStorage` instead of `CorpusStorage`. It exposes the identical 5-method surface +
`ensure_repo` and the same error classes, so `/storage` REST, the `storage_*`/`corpus_*` MCP tools,
and `corpus_detail` all read the **library bucket** with zero call-site changes. Specifics:

- **Owner scoping is the access control.** Object paths are `{sub}/{filename}` where `sub` is the
  verified JWT claim read from the `current_owner` ContextVar
  (`common.utils.request_context`), set *only* by `corpora_py.auth.AuthMiddleware` — never from
  client input. The service-role key bypasses bucket RLS, so this prefix is what stops one user
  listing/addressing another's objects. Paths match corpora-web's `{user_id}/{job_id}.corpus`
  layout. No verified identity (auth disabled) ⇒ un-prefixed bucket root, single-user local dev.
- **`hf_read_only` applies to both backends** — it is the deployment-wide storage read-only flag,
  refused inside `upload`/`delete` on this backend too, and the 403 dependency / MCP tool-skipping
  layers are backend-agnostic already.
- **`scopes_by_owner`** (`False` on `CorpusStorage`, `True` here) tells `corpus_detail._cache_key`
  to prefix cache entries and work dirs with the sanitized owner, so two owners' same-named
  archives never share an extraction. Local (job-result) registrations stay plain-name keyed —
  job ids are unique and job visibility is enforced upstream.
- Talks to the Storage REST API directly with `requests` (already a transitive dep); config is
  `SUPABASE_STORAGE_BUCKET` + `SUPABASE_SERVICE_ROLE_KEY` + `SUPABASE_URL` (or derived from
  `PROJECT_REF`), all unset ⇒ `StorageNotConfiguredError` (503) per call, never at import. The
  service-role key is server-side only — never in client config (no `VITE_*`).

This amends the previous "this service never talks to Supabase Storage" invariant: it now does
*iff* `STORAGE_BACKEND=supabase` is explicitly set; the default deployment still doesn't.

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

## Reference identifiers (`reference*.py`)

Node ↔ `corpus@version/Sec:...!otypeN` strings over stored archives, same one-implementation/two-surfaces shape:
`reference.py` (logic; caches one `tfref.Adapter` per loaded api in `_adapters`), `reference_api.py` (`/refs` router:
`POST /refs`, `GET /refs/resolve`, `GET|POST /refs/shortcode`), `reference_mcp.py` (`corpus_reference_create` /
`_resolve` / `_shortcode`; imports `fastmcp`, so excluded from `__init__` like the other `*_mcp` modules). Grammar and
rules are `common.utils.tfref` — see the root CLAUDE.md "Reference identifiers" section. All three routes are reads, so
`HF_READ_ONLY` does not gate them. Corpus id = archive stem, version = `manifest.yml` `version`; a reference pinning a
different version is refused (**409**), not silently re-resolved, because positional indices shift between builds.

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

## Typed job schema + transport guidance in /docs (`api.py`, issue #104)

The job payload is declared as `ConversionJobStatus` in `api.py` (mirrors `ConversionJob.to_dict()`
exactly — **change them together**; `TestOpenAPIContract` in `tests/admin/services/test_api.py`
guards the contract). `GET /convert` is `ConversionJobList`, `POST /convert` is
`ConversionAccepted`, and the error statuses are declared in the OpenAPI: 413 (upload cap) /
422 / 429 (queue full) on POST, 404 on poll, 404/409 on download and every job-scoped detail
route (`_JOB_DETAIL_RESPONSES`). The poll-vs-WebSocket guidance (serverless kills idle sockets
mid-job; polling is what advances a frozen instance; no real progress percentage) lives in
`_TRANSPORT_GUIDANCE` and is rendered into the POST + poll `/docs` descriptions via the decorator
`description=` kwarg — not the docstrings, because docstrings can't interpolate the size-limit
constants.

## Upload gate, category, post-conversion validation (`upload_validation.py`, `api.py`, `jobs.py`, issues #173/#176/#177)

`POST /convert` validates the upload **before** submitting the job (issue #173): `validate_upload`
(`upload_validation.py`) sniffs the first 4 KiB against magic-byte families and rejects with **422**
anything non-convertible (images/audio/video/non-zip archives/unknown binary/empty) or structurally
mismatched with the declared `source_format` (declared `pdf`, sniffed `zip`). Sniffing is
family-level on purpose — magic bytes can't tell EPUB from TEI-ZIP or TEI from XML, so textual
families cross-accept and the parser stays the authority past family level. Declared PDFs are
classified via `pdf_inspector`: `scanned`/`image_based` reject ("OCR is required"), `mixed` passes
with a 1-based skipped-pages warning logged onto the job, and an inspector *crash* (not a
`ValueError`) lets the upload through — the converter has its own fallback. The 422 `detail` is the
report dict (`declared_format`/`detected_format`/`convertible`/`reasons`/`warnings`/`pdf`).

The optional `category` form field (issue #176, `document`/`book`/`religious`) is forwarded to the
converter; the converter's resolved `ConvertedDataset.category` (an upgrade the tree can't express
is downgraded, with the warning logged on the job) is written to `manifest.category` via
`convert_to_corpus(category=...)`.

After `convert_to_corpus`, `_validate_converted_corpus` (issue #177) runs
`corpora_mcp.validate.validate_corpus_archive` (imported lazily — admin doesn't import
`corpora_mcp` at module load) and attaches its `.summary()` to the job via
`JobManager.set_validation` — it rides `to_dict()`/`ConversionJobStatus` as `validation`, on
FAILED jobs too (set before the raise). An invalid archive fails the job with
`ConversionValidationError` (a `JobFailedError` — the one exception family whose message `_run`
exposes verbatim in `job.error` instead of the sanitized `"Conversion failed: <type>"` form),
carrying the top-3 reasons. Test seam: the services conftest autouse-stubs
`corpora_mcp.validate.validate_corpus_archive` (call-time attribute) to always-valid; gate tests
re-patch that same seam.

## Transport-free pipeline seam (`conversion.py`, issue #188)

The end-to-end orchestration (display-name derivation → converter → `convert_to_corpus` →
post-conversion validation gate) lives in `conversion.run_conversion` — transport-free, reporting
progress through `on_log`/`on_display_name`/`on_validation` callbacks and raising
`ConversionError` (user-facing message, the issue #184 passthrough) / `CorpusValidationError`
(carries the validation summary). Two callers: `api._run_conversion` (wraps it with `JobManager`
bookkeeping and maps the errors to `JobFailedError`/`ConversionValidationError`) and the
`corpora` CLI (`corpora_py.cli` — terminal conversions with no server). Seams that must not
break: `api._run_conversion` passes `converters=CONVERTERS` / `convert_fn=convert_to_corpus`
from its own module globals at call time so the tests' `monkeypatch.setattr(api_module, ...)` /
`setitem(api_module.CONVERTERS, ...)` patches keep working, and the validator import stays lazy
inside `conversion.validate_archive` (the `corpora_mcp.validate.validate_corpus_archive`
call-time attribute the services conftest stubs). A converter `ValueError` naming a path in
`private_paths` is re-raised unwrapped so it stays behind the sanitized generic message.

## Converter errors reach `job.error` (issue #184)

Parsers/converters raise `ValueError` with deliberately user-facing messages ("ZIP contains
multiple Text-Fabric datasets: …"). `_run_conversion` wraps a converter-stage `ValueError` in
`JobFailedError` — the one family whose message `JobManager._run` exposes verbatim — so the user
sees the real reason instead of `"Conversion failed: ValueError (job id …)"`. Guard:
`_mentions_private_path` keeps any message naming the work dir, temp dir, or results root on the
sanitized generic form. Non-`ValueError` exceptions stay sanitized as before.

## Snapshot diff (`GET /convert/{job_id}/diff`, issue #151)

`?from=&to=` accept a history row's `id` or `label` (`_find_version_row`); the `current` row diffs
against HEAD, any other materializes its snapshot via `_materialize_version` (shared with
`/restore`: 404 unknown version / missing snapshot, 503 job-store trouble, 409 non-succeeded job).
`corpus_detail.diff_archives` compares the two zips' central directories only (member size +
CRC-32 — no extraction, no `.tf` content) and returns `files: [{path, kind, before?, after?}]`
with the history.yml `added`/`removed`/`modified` vocabulary; unchanged members are omitted.
Read-only: nothing is bumped, snapshotted, or republished.

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
TTL reap for the Hub caches. Shared job metadata + result bytes ship behind `JOB_STORE=supabase` (issue #140); the
default in-memory store is still per-process. (Converter-side gaps live in `src/admin/converters/CLAUDE.md`.)

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
- **Shared `JobStore` ships (`JOB_STORE=supabase`, issue #140).** `SupabaseJobStore` (PostgREST) +
  `SupabaseResultStore` (Storage, `conversion-jobs/` prefix) make poll and job-scoped detail
  instance-agnostic. Default remains `memory` (desktop sidecar / single-worker). Enable on Vercel with
  `JOB_STORE=supabase`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_URL` or `PROJECT_REF`, a jobs table
  (`packages/admin/sql/conversion_jobs.sql`), and `SUPABASE_JOBS_BUCKET` or
  `SUPABASE_STORAGE_BUCKET`. `HF_READ_ONLY` / Hub publishing is independent — do not paper over a
  missing job store by matching library rows against Hub filenames. The *executor* is still
  per-instance: a shared store shares *visibility*, not work distribution. A converting instance that
  dies mid-job stays `running` until the stall watchdog.
