# AI curation implementation

The backend contract is tracked in [#214](https://github.com/exegia/corpora-py/issues/214).
The implementation order agreed on 2026-09-18 is AI curation, then
[canonical references (#237)](https://github.com/exegia/corpora-py/issues/237), then
[desktop conversion (#187)](https://github.com/exegia/corpora-py/issues/187).

## Deliverables

1. [#232: Deterministic validation core](https://github.com/exegia/corpora-py/issues/232).
   Implemented in `corpora_py.ai.validation` and merged via #238.
2. [#233: Authorized validation and suggestions](https://github.com/exegia/corpora-py/issues/233).
   Validation is implemented through HTTP and MCP with caller access, scope membership,
   version/hash checks, and section-feature requirements. Suggestion persistence and
   rejection are implemented in #235; authoritative boundary/label comparisons and
   suggestion generation remain.
3. [#234: Apply, undo, and recovery](https://github.com/exegia/corpora-py/issues/234).
   Recovery core and explicit SQLite journal implemented in `ai.wal` / `ai.wal_sqlite`.
   Hosted journal mapping and atomic draft pointers are implemented in `ai.wal_supabase`.
   Typed archive editing and gated HTTP/MCP apply, undo, and history are implemented.
   Owned job-to-draft provisioning and reader/export APIs are implemented below.
   Corpus-wide confirmation remains before this issue can close.
4. [#235: Durable threads and suggestions](https://github.com/exegia/corpora-py/issues/235).
   Implemented with owned pinned scopes, explicit forks, messages, suggestion states,
   and durable Supabase/SQLite storage. Hosted rollout requires the migration below.
5. [#236: Streaming chat](https://github.com/exegia/corpora-py/issues/236).
   Integrate provider configuration, cancellation, and authorized curation tools.

## Validation core

`validate_nodes(api, corpus=..., version=..., nodes=..., required_features=...)`
returns the existing `ValidateResponse` shape. The input API must already be loaded
at the requested version, and the caller must authorize and resolve the selected nodes.
The core does not load paths, verify permissions, or interpret a client-supplied scope.

Required features come from trusted corpus schema metadata, keyed by concrete node
type. For example, `{"word": {"lemma": "str"}, "chapter": {"number": "int"}}`.
There are no universal lemma, label, or numbering assumptions. An unloaded required
feature is a configuration error, not evidence that corpus values are missing.

| Rule | Evidence |
|---|---|
| `OTYPE_MISSING` | The selected node lacks a nonblank string type. |
| `OTYPE_SLOT_MISMATCH` | The node's type conflicts with its position relative to `maxSlot`. |
| `OSLOTS_EMPTY` | A structural node has no slot links. |
| `OSLOTS_INVALID` | A structural node links to a non-integer or out-of-range slot. |
| `OSLOTS_UNREADABLE` | The loader cannot return the structural node's slot links. |
| `FEATURE_MISSING` | An explicitly required feature has no value for this node. |
| `FEATURE_TYPE` | An explicitly required feature is not the declared string/integer type. |

These descriptive identifiers are local rules, not claimed TF/RC rule-number mappings.
Structural findings point to a source walker rebuild. Feature findings need an
authoritative correction before they can become suggestions; the core does not mark
them automatically fixable. Boundary drift and label mismatch require additional
source/schema evidence and belong to #233.

This is a check of the loaded representation, not a replacement for archive round-trip
validation. It never clears caches, recompiles a corpus, or writes feature values.
`/ai/validate` and the combined server's `validate_node` MCP tool share the authorized
service described below. The response shapes are unchanged.

Run `uv run pytest tests/corpora_py/test_ai_validation.py tests/corpora_py/test_ai_contract.py`.

## Authorized validation

`POST /ai/validate` accepts the existing `{ "scope": NodeScope }` payload. Set
`scope.corpus` to a flat archive ID (with or without `.corpus`) in the configured
store, or `job:<UUID>` for a conversion result. Display titles, filesystem paths,
URLs, and names merely loaded into the shared CorpusManager are not access grants.
This clarifies the original stub's "loaded corpus name" description; clients using
mock names must supply a storage ID or owned job ID when integrating.

With auth enabled, the request needs a verified JWT identity. Job results require
that exact owner (including rejecting old unowned jobs); unknown and foreign jobs
both return 404. Supabase archive reads use the existing verified-owner prefix;
the configured Hub backend is the deployment's shared publishing library.
`AUTH_REQUIRED=false` retains the existing single-user local behavior. Published
and read-only archives can be validated because this operation never writes them.

Each call downloads/copies an archive into a private temporary directory. Manifest
version, API, and findings come from that one snapshot; neither the global loaded
corpus registry nor the corpus-detail cache is used. The loader may compile caches
in that temporary copy, but the source archive is unchanged.

```json
{
  "scope": {
    "corpus": "mini",
    "version": "v1.0",
    "level": "passage",
    "node_id": 9,
    "node_type": "paragraph",
    "label": "First paragraph"
  }
}
```

Word scope checks one slot; structural scope checks its anchor and embedded nodes.
Section and document scopes must match the declared section hierarchy. Corpus scope
checks every node and must omit node/type/range. A passage range selects same-type
sibling units under the same nearest declared section in **document order**, not an
integer interval of node IDs. Its anchor must be its first unit or a containing node.
Cross-section ranges and mismatched node types return 422 instead of widening the scope.

`v1.0` and `1.0` identify the same version. Other version mismatches return 409 with
the existing top-level `ErrorInfo(code="stale", current_version=...)`. Optional
`content_hash` is `sha256:<hex>` over UTF-8 default-format text for the unique selected
slots in slot order, with no trimming, normalization, or extra separators. A mismatch
also returns 409. Feature-only changes still require version bumps; the later apply
service must compare displaced feature values as well as the text hash.

Required section features and their types come from the loaded `otext` schema. Other
linguistic requirements and source-based boundary/label comparisons are not inferred.
Infrastructure errors return a generic 503; unreadable archives return 422; absent
identity at the service boundary returns 403 (the HTTP middleware normally returns
401 earlier). Suggestion generation and chat remain pending. Durable threads, rejection, and gated mutations are implemented below.

Run `uv run pytest tests/corpora_py/test_ai_service.py` for HTTP, MCP (including real
ASGI transport), ownership, scope, and stale-selection coverage.


## Durable conversations (#235)

Hosted deployments default to `AI_STORE=supabase`, using `SUPABASE_API_URL`
and `SUPABASE_SERVICE_ROLE_KEY`. Apply
`packages/admin/sql/migrations/20260918141622_ai_thread_persistence.sql`
to the target database before enabling these endpoints. This migration has only
been tested locally; merging the code does not deploy it. The new table has RLS
and no browser-role grants or policies. All access goes through the API, which
filters by verified owner and rechecks current corpus access on every request.
No outage fallback creates ephemeral or divergent local state.

For a persistent single-host installation, explicitly set `AI_STORE=sqlite`
and optionally `AI_SQLITE_PATH` (default: platform user-data directory,
`corpora/ai-threads.sqlite3`). The local owner is available only when auth is
explicitly disabled. Mount this file's directory on durable storage; SQLite is
not a multi-instance hosted backend.

The following additive contract is for corpora-web#108:

| Operation | Endpoint | Body / pagination |
| --- | --- | --- |
| Create thread | `POST /ai/threads` | `{scope: NodeScope}` |
| List threads | `GET /ai/threads?corpus=...` | `limit` 1–100, opaque `cursor`; response `next_cursor` |
| Read thread | `GET /ai/threads/{id}` | Original pin and ordered sections |
| Explicit scope fork | `POST /ai/threads/{id}/sections` | `{scope: NodeScope}`; returns thread |
| Append user message | `POST /ai/threads/{id}/messages` | `{section_id, content}`; returns message |
| Read messages | `GET /ai/threads/{id}/messages` | `limit` 1–100, `offset`; response `next_offset` |
| Read suggestions | `GET /ai/threads/{id}/suggestions` | Same offset pagination |
| Reject suggestion | `POST /ai/suggestions/{id}/reject` | No body; 204 |

Create, fork, and append accept an optional UUID `Idempotency-Key` header.
Retry the same operation with the same key and payload. Reusing a key with a
changed payload returns 409. Navigation does not update the original pin;
explicit forks validate the new scope and retain earlier messages and snapshots.
Historical reads remain available after a corpus version changes, provided the
caller still has access. Published corpora permit conversations without edits.

Only trusted server producers can append assistant/tool messages or save
suggestions. `save_suggestion` returns a thread-qualified opaque ID; use that
returned ID in events and subsequent operations. Suggestions must match their
section's scope, base version, and supplied content hash. Pending suggestions can
become applied, rejected, or stale; terminal transitions are idempotent and cannot
be changed to another terminal state. Applying is handled transactionally by #234's WAL
transaction; this storage service itself never edits corpus content.

Updates use revision compare-and-swap, retrying contention up to five times.
Threads are bounded to 256 sections, 2,048 messages, 512 suggestions and 2 MB of
serialized state; exceeding a bound returns 413. Start another thread when full.
Backend failures return generic 503 responses. Provider keys are never accepted
by persisted message models or copied from headers into storage.

Run `uv run pytest tests/corpora_py/test_ai_threads.py` for persistence, ownership,
retry, pagination, lifecycle, HTTP and concurrent-write coverage. For isolated
PostgreSQL, initialize the Supabase roles and `auth.users`, apply the migration,
then run `packages/admin/sql/tests/ai_thread_persistence.sql` with `psql`.


## Write-ahead recovery core (#234, first slice)

`MutationEngine` implements apply, retry, recovery and undo against explicit
`Journal` and `Drafts` protocols. `SQLiteJournal` persists the complete intent
before publication and preserves the first successful publication timestamp.
This is an explicit single-host implementation, never a hosted outage fallback.
No public endpoint uses this engine yet.

The draft adapter stages a complete multi-field change and supplies immutable
before/after evidence: unique revision, full-draft digest, version, scope text
hash and target feature values. The engine checks all displaced values and the
entire resulting feature map. Missing fields, no-op rows, duplicate fields,
stale scope/version/hash and mismatched staged output cannot be journaled.

Publication must atomically compare the entire before state, recheck current
permissions/locks, replace the draft, and retain a receipt bound to the exact
intent. Every archive writer must participate in that same protocol. Receipt
lookup must be strongly consistent with HEAD reads. A mutex around the existing
unconditional upload is insufficient across API instances and other writers.

Recovery classifies a pending intent as follows:

| Evidence | Result |
| --- | --- |
| Matching durable publication receipt | Finalize applied, using the original publication time |
| Exact before evidence, no receipt | Not applied; safe to retry through conditional publication |
| Anything else, including exact after data without a receipt | Conflict; retain pending intent for explicit recovery |

Receipts survive later changes, so a crash after publication but before journal
finalization remains recoverable after HEAD advances. A changed hash alone is
never proof of success. Recovery does not silently mark ambiguous rows failed.

Undo creates another intent with the inverse complete diff and stable links to
all original field entries. It requires the original after evidence to still be
HEAD; even an intervening revision with identical values blocks undo. Repeated
undo returns the same result. The original entry remains immutable. Each field
entry retains both `#corpora-ai` and the verified applying user in `resp`.

### Hosted integration still required

The deployed `public.corpus_changes` schema was inspected on 2026-09-18. It
requires `document_id` referencing `corpus_documents` and `applied_by` referencing
`public.users`. Its suggestion index is **not unique**; `reverts_change_id` is
unique. Archive IDs and `job:<UUID>` references currently do not resolve that
document relationship. Do not infer it from an archive filename or recreate the
existing table.

The next slice must resolve caller-owned documents, add conditional draft
publication with retained receipts, and map a whole operation into field rows in
one database transaction. Persist operation grouping plus both evidence snapshots
and the receipt binding. Stable field UUIDs from `Intent.entries()` can be used as
`corpus_changes.id`; each undo entry links its corresponding original field row.
The public mutation API below retains `ApplyResponse.change` and adds
`changes` for the full group.

Archive `history.yml` remains the version/snapshot timeline. The staged archive
must carry the operation provenance and version bump; `corpus_changes` supplies
field-level displaced readings and responsibility. `commit_id` is linked when the
working version is committed. Readers/exporters must retain that provenance.
Provider credentials belong in neither store.

Production wiring below resolves owned suggestions, checks target membership and
field types, enforces locks, synchronizes suggestion state, and exposes HTTP/MCP
mutations and scoped history. Retries reconcile durable pending operations.
Corpus-wide confirmation remains closed with 428 until bound tokens are connected;
#234 remains open.

`tests/corpora_py/test_ai_wal.py` uses a transactional SQLite draft fixture to test
the adapter contract, not the production archive writer. It exercises journal
failure, crashes before/after publication and during finalization, restart,
concurrent writers, multi-field edits, stale/locked/foreign operations, bound
confirmation, ambiguous recovery, receipt integrity and undo.


## Hosted journal and immutable draft heads (#234, second slice)

`SupabaseJournal` implements the recovery engine's durable journal protocol using
`HostedStorage` and the server-only `corpora_ai_storage` Postgres function. The
migration is `packages/admin/sql/migrations/20260918154935_ai_hosted_journal.sql`.
It has been verified on isolated PostgreSQL 17, **not applied to the live project**.
The earlier thread-persistence migration also remains a separate rollout prerequisite.

`corpus_ai_drafts` explicitly binds a verified owner and corpus reference to an
existing `corpus_documents.id`. Provisioning is trusted server work: the existing
document table has no ownership field and its path/job metadata cannot establish
ownership. `HostedStorage.register()` is not an HTTP/MCP endpoint and must only be
called after the source object's ownership has been established. Registration
checks the initial object bytes and cannot silently rebind an existing document.
There is no fallback from an unknown reference to a guessed filename or document.

Draft archive bytes use the dedicated private `corpus-ai-drafts` bucket with keys
`{owner}/ai/{document_id}/{revision_uuid}.corpus`. Uploads disable upsert; duplicate
uploads succeed only when downloaded bytes match the expected SHA-256 digest.
Publication verifies the staged object again. A database transaction checks the
old revision, full-archive digest and version, updates HEAD, and stores the exact
intent receipt and publication time. Locks are checked under the same row lock.
Competing publications cannot both win. Existing flat archive uploads cannot
address these immutable revision objects.

`corpus_ai_operations` stores the full intent and receipt. Inserting an operation
also inserts **all** of its field rows into the existing `corpus_changes` table in
one transaction. Any invalid field rolls back the complete group. Finalization
requires the publication receipt and marks the whole group applied using its
original timestamp; it is idempotent and works after HEAD advances or is locked.
Undo rows retain the existing per-field `reverts_change_id` links and uniqueness.
The pending-batch method is bounded to 100 rows; a background recovery worker is
not enabled yet.

### Access and retention

The two new tables have RLS and no browser-role grants. The RPC uses security
invoker, an empty search path, and service-role-only execution. Its owner argument
must come from verified server identity, never an HTTP request body. Invalid or
unavailable upstream responses become generic storage errors; credentials remain
only in server headers. See the official [database function permissions guidance](https://supabase.com/docs/guides/database/functions).

A restrictive policy makes new AI `corpus_changes` rows visible only to their
applying owner; legacy rows keep their prior visibility. Browser roles lose
TRUNCATE permission on this log because TRUNCATE bypasses RLS. Another restrictive
policy denies browser access to the dedicated bucket even if another permissive
storage policy exists. Registration and operation foreign keys restrict deletion
of documents with retained history. Garbage collection and account/document
removal need an explicit retention workflow; do not delete receipt-bearing objects
or operation rows as temporary upload cleanup.

The live security advisor was read before preparing the migration. It reports
pre-existing policy/exposure and mutable-search-path findings outside these new
objects; this migration does not claim to remediate the whole project. Relevant
[Supabase advisor checks](https://supabase.com/docs/guides/database/database-linter)
are additionally asserted against the isolated schema: RLS, private bucket,
function privileges and invoker mode.

### Verification and remaining wiring

The PR `check` job starts PostgreSQL and includes the database integration tests in
`make ci`. Locally, start an isolated `postgres:17-alpine` container, initialize the
`anon`, `authenticated` and `service_role BYPASSRLS` roles, then run:

```sh
CORPORA_AI_TEST_POSTGRES=<container-name> uv run pytest tests/corpora_py/test_ai_hosted_storage.py
```

Tests create and drop a temporary database in that container. The bootstrap SQL
under `packages/admin/sql/tests` is test-only and must never run on a live project.
The tests exercise the real migration/RPC transactions and the recovery engine
through those transactions. Object HTTP upload/read-back is tested with mocked
transport; no hosted bucket was changed during verification.

The archive editor and public mutation integration below build on these transactions.
#234 remains open for bound corpus-wide confirmation.


## Typed archive editing (#234, third slice)

`ArchiveDrafts` now connects the mutation engine to the hosted draft storage port
with real archive inspection and staging. `edit_archive()` creates a private copy,
checks the registered digest/version, resolves the pinned scope, and checks the
complete displaced-value diff before touching even that copy. The input archive
is never overwritten. Staged archives are uploaded under the new revision key;
the journal/conditional publication protocol still controls when they become HEAD.

This adapter supports existing string and signed 64-bit integer **node features**
in archives retaining all Text-Fabric source files. It rejects unknown features,
paths, graph/topology features, boundary suggestions, source-text suggestions, and
all features referenced by declared text rendering formats. Unsupported repairs
must use the source/walker workflow. Corpus-wide edits return 428 until the panel's
bound confirmation protocol is wired; a nonempty token is never accepted as proof.

For a valid feature edit, the adapter serializes complete changed feature maps,
rebuilds the `.cfm` cache, refreshes computed TOC data, and increments the archive's
major.minor version. It then reloads the result and verifies the exact target diff,
scoped text, and every untouched node/edge value. Source/cache disagreement that
would alter other content fails before an output archive can be published. TOC
identity/publisher metadata and unrelated assets are preserved.

`history.yml` retains earlier entries and snapshot pointers. Its new entry and
`ai-changes.json` carry the stable operation ID, suggestion, pinned scope, target,
complete old/new diff, base revision, and AI plus verified-user attribution. Undo
adds another version and records the original operation link; it does not erase
the displaced readings. These archive timestamps describe staging; the durable
publication receipt remains authoritative for the database's `applied_at`.

Real archive tests cover rebuilding and reloading CF caches, typed labels,
multi-field edits, string escaping, unchanged assets, inverse edits, operation
provenance, stale/out-of-scope requests, source-text protection, and cache drift
outside the selection. An engine/adapter round trip uses actual archive files and
a durable SQLite journal with a local conditional-publisher fixture. Hosted
publication transactions remain covered by the PostgreSQL tests from the previous
slice. No live archives or migrations were changed.

## HTTP/MCP mutations (#234, fourth slice)

`AI_MUTATIONS_ENABLED=true` enables apply, undo, and history for **already provisioned,
owned hosted drafts**, using `AI_STORE=supabase`. The default remains false (501).
A verified caller identity is required even if general authentication is disabled.
A database capability check refuses writes if the guard migration is missing.
This setting requires all three versioned migrations, in order:

1. `20260918141622_ai_thread_persistence.sql`
2. `20260918154935_ai_hosted_journal.sql`
3. `20260918165018_ai_mutation_api.sql`

These migrations have only been exercised in disposable PostgreSQL databases;
no production schema or corpus has been changed by this work. Registration remains
a trusted server operation after source ownership is verified. Knowing a global
`corpus_documents.id` does not establish ownership and never provisions a draft.

`POST /ai/suggestions/{id}/apply` resolves the suggestion from the caller's thread.
The publication transaction locks the draft, operation, and thread; compares the
entire stored suggestion payload and pending status; then changes HEAD, records
its receipt, marks the suggestion applied (incrementing the thread revision), and
finalizes every field's history entry together. A rejection that wins the thread
lock first prevents publication. A rejection with a stale revision reloads the
applied status and returns 409. Failed transactions roll back all these changes.

Apply responses retain the original `change` field and add `changes` plus
`operation_id`. Every history entry also carries its operation ID.
`POST /ai/changes/{change_id}/undo` accepts any field change from an owned operation
and reverses the **whole group**. It retains `revert` for the selected field and
adds `reverts` for all affected fields. Retries use the durable operation ID and
do not create duplicate versions. Intervening edits prevent undo (409); published
or locked drafts reject writes (423). History remains readable while locked.

`GET /ai/changes?corpus=...&node_id=...&limit=50&offset=0` returns only the caller's
applied AI entries, newest first, with `next_offset`. Limits are 1–100; node filtering
is optional. Offset pages describe the current history; refresh from offset zero
after new edits. MCP tools `apply_node_fix`, `undo_change`, and `get_change_log`
use the same service and ownership rules.

With mutations enabled, AI validation and thread access resolve the owned draft
registry before the legacy archive/job source. Registered corpora load verified
HEAD bytes, so old pinned versions correctly become stale. Registry errors fail
closed; only an absent registration can use the legacy read path. Legacy storage,
corpus-detail caches, and non-AI readers are not redirected by this slice. Explicit `draft:<UUID>` references (below) resolve HEAD even when writes are disabled.
Legacy flat registrations still require the setting for HEAD lookup.

Real-archive tests drive the new SQL function through HTTP and MCP, including
multi-field apply/undo, retry identity, pagination, ownership, locked drafts,
registered-HEAD validation, and both orderings of the rejection/publication race.
Corpus-wide confirmation still returns 428, including for arbitrary nonempty
strings. Source-text and boundary repairs remain unsupported. Owned draft provisioning and reader integration are described below.
Next: the bound corpus confirmation protocol.


## Owned working drafts and readers (#234, fifth slice)

`POST /ai/drafts` accepts `{ "job_id": "<conversion UUID>" }`. The verified caller
must exactly own a succeeded conversion job; anonymous legacy jobs, another
user's job, and arbitrary global document IDs do not qualify. The service copies
the result into a private temporary directory, checks the archive and retained TF
sources, stages immutable bytes, and then creates the document and draft binding
in one database transaction. Non-archive ingest results are rejected.

Provisioning requires `AI_MUTATIONS_ENABLED=true`, `AI_STORE=supabase`, a writable
deployment, a corresponding `public.users` profile, and migration
`20260918180400_ai_owned_drafts.sql` after the previous three AI migrations. The
capability check refuses provisioning against an older database. This migration
has only been tested in isolated PostgreSQL; it has not been applied live.

A deterministic document ID gives each owner/job pair one working draft.
Concurrent creation uses a transaction lock and returns the first binding; a
retry after edits returns current HEAD and never replaces it with the source.
The original job archive remains unchanged. Upload failure cannot create a
binding. A failed database transaction or a concurrent losing initializer can
leave an unreferenced staged object; retention-aware cleanup is still separate.

Responses contain `id`, `corpus` (`draft:<UUID>`), `version`, `revision`, `digest`,
`state`, and an authenticated `archive_url`. Use **that corpus identifier and
version** when creating a pinned AI thread or validating a scope. Drafts are listed
through `GET /ai/drafts?limit=50&offset=0` (1–100, ordered by ID); a detail lookup is
`GET /ai/drafts/{id}`. Creation retries still check the source job; existing draft
reads do not depend on the job's result remaining locally available.

The reader uses these authenticated routes under `/ai/drafts/{id}`:

| Route | Result |
|---|---|
| `/manifest`, `/index`, `/versions` | Metadata, section navigation, and version timeline |
| `/nodes/{node}` | Current node text, features, context, and annotations |
| `/sections?parent=...&offset=0&limit=50` | Section navigation (limit 1–200) |
| `/content?ref=...&fmt=...&offset=0&limit=50` | Paginated passages (limit 1–200) |
| `/archive` | Verified current `.corpus` bytes, including edits and provenance |

JSON reader responses are `{ "draft": <snapshot metadata>, "data": <existing
corpus-detail shape> }`. Each read resolves and verifies one immutable HEAD,
then uses a private per-call extraction; it never registers an archive in the
shared corpus-detail cache. Version reads use `history.yml` or manifest metadata;
they do not execute Git against archive-supplied configuration. The returned revision tells clients which snapshot
the view describes. The archive response sets its digest ETag, `X-Draft-Revision`,
and `Cache-Control: private, no-store`, and removes its temporary download after
serving it. No signed storage URL or service key is exposed.

Explicit draft references never fall back to shared storage, even if not found.
Reader/export/validation access continues when mutations are disabled or a draft
is locked. Legacy `/storage` and conversion-job routes continue to represent their
original artifacts; clients must use the draft routes for working-copy content.
MCP provides `create_working_draft`, `list_working_drafts`, and
`read_working_draft` with the same ownership and snapshot rules.

The migration adds `corpus_documents.ai_private` and a restrictive policy so
private draft metadata cannot leak through the legacy broad read/insert/delete
policies. Browser roles cannot insert private rows, change private rows back to
public, or truncate the table. Existing draft bindings are marked private; normal
legacy records retain their existing access. Server-mediated draft responses
remain owner-scoped. The deployed source/status check constraints are preserved
(`source=upload`, `status=converted` for the newly uploaded working copy).

Verification covers the actual create → thread → apply → reader/export → undo
flow, immutable source preservation, both HTTP and MCP, concurrent provisioning,
foreign/anonymous/incomplete jobs, legacy metadata privacy, disabled-write reads,
missing-draft fail-closed behavior, and upload failure without a document binding.
