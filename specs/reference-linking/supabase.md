---
title: Offline Supabase reference storage proposal
description: Private storage, authorization and transactional adapter contracts.
tags: [references, supabase, storage, review]
---

# Scope and authority

[Proposed SQL](supabase-proposal.sql) is a design artifact outside migration directories.
It has not been applied. The repository currently has no Supabase migration directory
or reference database client to extend. The reusable core remains unchanged.

The production working database is authoritative. Published C-USX and approved JSON
snapshots are projections with matching reference UUIDs, never parallel working stores.
The existing graph contract and bounded USX `jmp` renderer remain intact; whole-document
selector embedding still requires an agreed C-USX contract. No schema column requires
paragraph IDs or sentence numbering. Pinned document identities, typed locators and
original/converted mappings remain validated core JSON, including normalization and
coordinate conventions defined in the specification.

A proposed space is an authorization boundary, not a corpus/document identifier.
Confirm its mapping to Corpora's account/team model before creating migrations.
Composite keys keep history and event references within a space. The same stable UUID
may exist in separate working authorities after import; imports never allocate a new
UUID merely to hide a conflict. `authority_id` is configured by the server, not accepted
as a user's claim to another authority.

# Storage

| Table | Responsibility |
| --- | --- |
| spaces / memberships | Server-managed boundary and independent capabilities |
| resource_access | Explicit per-user exact resource scopes; independent of space capabilities |
| entitlement_heads | Provider-bound version/digest and last complete grant snapshot |
| heads | Current version pointer, with a deferred foreign key to its snapshot |
| revisions | Immutable-by-adapter reference JSON, actor, reason, action, validation and conversion evidence |
| discovery_revisions / discovery_events | Append-only scholarly intake decisions and registration retry identity |
| conversion_events | Explicit authority/event identity, detector revision, canonical fingerprint and original report |
| publication_events | Acknowledgment or withdrawal, exact approved/resulting versions and artifact digest |

Resolution, review and publication stay separate fields of the reference snapshot.
There are no competing mutable status columns. SQL checks a small set of envelope
invariants; full Pydantic model validation, fresh resolver verification and legal
transitions remain adapter obligations. A stale anchor is a validation result, not a
new reference resolution enum. Actor UUIDs come from verified authentication, while
provenance retains the original creator or detector. Historical actors survive account
deletion; membership removal immediately removes future access.

The schema grants history/event INSERT and head-pointer UPDATE to the server
role. Membership UPDATE and space authority UPDATE are also required for FOR SHARE row
locking; the privileged server credential can therefore mutate these values and must
remain trusted. Resource grant rows likewise require server UPDATE privilege for locks. It does not make logs tamper resistant against database owners, ensure contiguous
versions by itself, or implement transitions without the adapter. Snapshot bytes and
external delivery/removal receipts are future artifact storage work; the ledger digest
alone is not proof that C-USX was delivered or removed.

# Authorization contract

Keep `reference_working` outside exposed API schemas. All ten tables enable RLS with
no client policies, and schema/table grants deny `anon` and `authenticated` access.
Read and write requests go through the server adapter; no browser service key, direct
client mutation, or SECURITY DEFINER RPC is introduced by this proposal.

Supabase's service role bypasses RLS. The adapter must verify a user JWT using the
repository's JWKS authentication boundary, derive actor identity from it, and check
current membership inside each transaction. Never use request-body actor IDs,
`user_metadata`, stale JWT membership claims, or a configured service credential as
proof of the caller's rights. Reads require any membership. Capabilities are independent:
`contribute` allows edit/resolve/import/conversion; `review` allows approve/reject;
`publish` allows acknowledgment/withdrawal; `admin` manages membership and may explicitly
exercise all capabilities. Reopening a withdrawn record requires contribute. Automated
jobs require an explicitly provisioned authenticated principal, not implicit access to
all spaces. Space/member creation and removal need a separate privileged administrative path.
Resource grants have a distinct authenticated admin synchronization path.

Lock the matching membership rows with FOR SHARE for the transaction, so concurrent
revocation serializes with the authorized operation. Membership administration must
use ordinary transactional row mutations. Server checks reject cross-space IDs and resources without explicit access grants.
A grant is authorization, not proof that the document exists or its anchor resolves. If direct client reads are introduced later,
add reviewed membership-based SELECT policies and grants, plus tenant-isolation tests;
do not simply expose this schema.

# Transaction contracts

Use one PostgreSQL connection and transaction per operation; separate REST calls cannot
atomically append history and advance a head. A future adapter should share lifecycle
contract tests with SQLite and use parameterized SQL.

1. Verify authentication, lock membership and enforce the operation's capability.
2. For an existing reference, SELECT its head FOR UPDATE and compare expected_version.
   A mismatch returns a conflict without writing. For creation, require no existing head;
   a concurrent unique-key conflict rolls back and returns a conflict. Lock multiple
   heads in UUID order. Insert the head and revision together using deferred constraints.
3. Validate complete models and reuse the existing store's transition rules. Approve
   verifies fresh pinned source and target, records evidence and an explicit reason for
   the limited external-work exception. Ambiguity/stale physical anchors cannot be
   overridden. Edits invalidate approval; published records require withdrawal before
   reopening. Clear obsolete conversion evidence when source identity changes.
4. Append version n+1 and update the head in the same transaction. No revision update
   or deletion occurs. Identical saves are idempotent only after expected-version checks.
5. Commit; return the audited version, not just the asserted reference JSON.

Conversion registration locks the authority/event identity (a transaction advisory lock
or unique-key retry), compares the existing canonical fingerprint, and returns the
original report/UUIDs on identical retries. Changed requests conflict. New event and all
new references commit together, including empty reports; ID collisions roll back the
entire operation. Passage text is never a deduplication key.

Import planning matches stable IDs and semantic content as the snapshot adapter does.
New imports become pending drafts/unresolved; identical snapshots do not overwrite
review; conflicting working content requires reconciliation. Upstream version numbers
are evidence, not the local version sequence. Apply each decision with explicit CAS;
a batch is not atomic unless a separate batch contract is implemented.

Export reads audited approved/published current heads in one repeatable-read snapshot,
preserving UUIDs and working versions. Export does not mark publication. Acknowledgment
locks the head, verifies authority, exact approval version/content and snapshot digest,
and appends both publication event and resulting revision atomically. Retry event IDs
must bind the entire request. Withdrawal records a tombstone and excludes the record
from later exports; it does not claim remote removal. These rules initially retain the
local ledger's single-active-artifact-per-review-cycle limitation.

# Validation before implementation/deployment

The SQL and bounded working-store adapter have now been exercised against disposable
local PostgreSQL 17 with fixture Supabase roles and auth.users. No Supabase project
or live database was accessed. This is not a complete production Supabase integration. Before a migration is authorized,
run a disposable local database suite covering missing/expired authentication,
cross-space reads/writes, forged actors, independent capabilities, membership revocation
races, denied direct client writes, immutable history grants, null/malformed envelopes,
concurrent CAS, event retries/conflicts and complete rollback. Also verify review
exceptions, stale anchors, published-edit rejection, imports and withdrawal replay.

Confirm production space ownership, retention/deletion policy, user-independent jobs,
artifact storage and authenticated read transport. Then implement the adapter outside
the core, generate a repository-compliant migration and review it separately. Deployment
remains a separate authorized action.

Design references checked: [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
and [database testing](https://supabase.com/docs/guides/database/testing). The public
changelog endpoint returned HTTP 403 in this environment; no changelog verification is
claimed. No live project was queried or modified.

# Implemented bounded adapter

`corpora_py.linking_postgres.PostgreSQLReferenceStore` is an optional server adapter
installed with `corpora-py[linking-postgres]`. Supply trusted DSN, space UUID, JWKS URL,
audience and the caller's JWT. It verifies the JWT before any database connection and
again for each read/write, derives the UUID subject, and checks database membership
inside each transaction. Do not construct it from untrusted connection/authentication
configuration. It never creates schemas or provisions memberships. The repository
JWKS verifier's existing validation behavior applies; immediate session revocation
still require a trusted entitlement provider and application boundary.

Creation, history, get, save, target resolution, approval/rejection and withdrawn-record
reopening reuse the SQLite adapter's public lifecycle methods and a shared pure revision
builder. PostgreSQL owns CAS, head locking, membership locking and atomic append.
The separate event adapters now implement conversion-event registration, publication
acknowledgment/withdrawal and repeatable-read export. HTTP routes, production entitlement-provider
wiring and connection pooling remain pending. Do not substitute
per-reference reads for a coherent production export transaction.

Tests require the optional extra and `LINKING_TEST_POSTGRES_DSN` pointing to an explicitly
loopback, disposable empty database with administrative privileges. They provision
fixture roles/auth schema and the proposal, then remove those fixtures. Never aim them
at a developer's persistent database. Without the variable they skip. Authentication
in these storage tests uses controlled verifier results; cryptographic verification
is provided and tested separately by the existing JWKS module.

# PostgreSQL events and publication

`PostgreSQLConversionEventRegistry(store)` and `PostgreSQLPublicationLedger(store)`
in `corpora_py.linking_postgres_events` obtain authority from the space row, never
a user-supplied authority assertion. Membership and authority rows are locked while
the transaction operates. Event advisory locks serialize retries; detected reference
inserts occur in UUID order. Hash collisions only serialize independent operations.
Retries still require current capability and a valid token. Conversion fingerprints
use the same pure validation/fingerprint helper as SQLite, exclude allocated UUIDs
and retain all original IDs/evidence in the event record. Empty reports are durable.

The proposal now stores validated full event JSON alongside indexed envelope fields.
Only the adapter writes both representations; these records are not independently
editable lifecycle authorities. Publication retries bind reference, action, actor,
reason, expected version and artifact digest. Event and working revision insertion
commit together; failures roll back head changes. Withdrawals retain the approved
version/digest and leave tombstones for a future delivery adapter. Export reads current
heads in one repeatable-read transaction and omits withdrawn references. A concurrent
conflicting transaction may require a caller retry; the adapter does not guess a new
expected version. The single-active-artifact limitation remains.

# Exact resource access

Every PostgreSQL operation now requires resource grants independently of space
capabilities, including administrators. `resource_access` keys space, verified user
and SHA-256 of canonical endpoint scope JSON. The scope includes work, edition,
package, exact revision and document, preserving null fields. Only locators are
excluded, so passages in one pinned resource share a grant. Stored JSON must also
equal the requested scope; matching a hash alone does not authorize another scope.
Work-only or edition-only grants authorize exactly that scope, never its documents
or later versions. No implicit public-work or wildcard access exists.

Reads check all endpoints before returning typed data. Working history checks every
revision, including old sources/targets and resolver candidates. Writes check both
previous and replacement snapshots and retained validation/conversion evidence.
Original-file mappings require their own grant as well as converted text. Conversion
event reads/retries check the whole saved report, including empty reports' source
snapshot. Ledger reads/replays check associated working history; exports check all
evidence in the exported current revision, including withdrawn entries before
omission. Any denied resource rejects the operation; no partial quotes, candidates
or snapshot are returned. A caller needs grants for old evidence to read history,
even if the current reference now points elsewhere.

Grant rows lock FOR SHARE until transaction end, serializing revocation through
ordinary row deletion/update. This does not retract data already returned to an
authorized caller. PostgreSQL can abort concurrent operations with deadlock or
serialization errors; callers may retry the same operation and expected version,
never silently advance CAS. Administrative credentials remain trusted.

The working store does not provision or infer grants. The separate admin synchronizer
now atomically applies an explicit complete snapshot. A future application boundary must
map Corpora's corpus/document entitlements to these exact scopes using a trusted
inventory, and must provision original and converted scopes explicitly. Unresolved
cited works require their own work-scope grant; approval exceptions cannot bypass
authorization. Deleting a document does not automatically invalidate a grant; inventory
availability and exact resolver verification remain distinct responsibilities. Entitlement-provider verification and HTTP wiring remain staged. No
production account model or live database has been changed.

# Session checks and entitlement synchronization

Each PostgreSQL operation now requires a verified JWT with UUID `sub` and `session_id`.
The subject/session pair must exist in `auth.sessions`, with `not_after` either null
or later than the database clock. The proposal grants the server SELECT only on
`id`, `user_id`, and `not_after`; no auth-session mutation or lock privilege is added.
Missing/malformed claims fail before adapter construction opens a database connection.
Subsequent operations reverify the JWT and database session. Deleted signed-out sessions,
wrong-user sessions and expired session deadlines fail even while a JWT remains signed
and unexpired. Database failures fail closed; there is no offline session bypass.

This is an operation-start check, not cancellation of operations already authorized
or retraction of returned content. It does not implement GoTrue's inactivity timeout,
single-session policy or refresh-token revocation algorithm. Supabase documents that
some session policies are evaluated on refresh and expired rows may remain temporarily;
row existence alone is insufficient, hence the explicit deadline check. Confirm the
production auth schema and policy requirements before deployment. The general app's
existing authentication middleware is unchanged.

`PostgreSQLEntitlementSynchronizer(store, provider_id=...)` requires the initiating
user's current session and admin capability. `synchronize(target_user, snapshot,
expected_version=...)` takes an `EntitlementSnapshot` with provider identity/revision
and explicit unlocated resource Endpoints. The target must belong to the same space.
One configured provider owns the whole grant set for that user/space. No inheritance
from work names, corpus paths, JWT metadata or user assertions occurs. Original-file
and converted-text resources must both be listed; locators and duplicate scopes
are rejected. Empty snapshots revoke all resource access.

Synchronization locks the target, compares the local version, and atomically replaces
grants and its provider-bound head. Initial adoption uses expected_version=None and
explicitly replaces any manually provisioned grants. Later calls require the current
version. Identical provider content/grants are idempotent independent of endpoint
order; changed snapshots or drift repair advance the local version. Stale calls and
provider takeover attempts fail. Provider revisions are opaque evidence, not sortable
local version numbers. The application must verify freshness/authority when fetching
provider evidence; this adapter cannot establish that an input snapshot is truthful.
The mutable synchronization head is not an immutable grant audit ledger.

Corpora-py currently has no authoritative entitlement table or callable provider contract.
The synchronizer therefore remains a trusted integration seam, with no HTTP route or
automatic registration hook. Never pass a client request body directly to it. A production
provider must obtain and verify actual ownership/shared-access entitlements before
constructing snapshots; multiple providers require an agreed union/ownership design
instead of repeatedly replacing each other's grants. No existing ownership policy
is invented or changed by this implementation.

Current design reference: [Supabase user sessions](https://supabase.com/docs/guides/auth/sessions).
Local tests use fixture auth tables/controlled JWT claims, not a live Supabase project.

# PostgreSQL scholarly discoveries

`PostgreSQLDiscoveryStore(store)` in `corpora_py.linking_postgres_discoveries`
implements the same discovery history, registration fingerprint, catalog refresh,
rejection and work-selection rules as SQLite. Shared pure helpers prevent lifecycle
rules from diverging. Reads verify sessions, membership and every retained endpoint
in history; registration/refresh require contribute capability, while rejection and
work selection require review capability. Selection creates a pending unresolved
working Reference atomically with its decision, not an approved passage link.

Authority is obtained from the configured space. Registration and discovery advisory
locks serialize initial retries and subsequent CAS without mutable history pointers.
Unknowns need only source-resource access; identified candidate works and native
mapping evidence each need explicit grants. Revoked grants block retries and history
reads. Append-only schema grants prohibit direct client access/history rewrites.
Typed record JSON carries all IDs, actors, reasons, UTC times, mapping evidence and
unchosen hypotheses. The schema remains an unapplied proposal outside migrations.

Tests run only on disposable local PostgreSQL, including concurrent retries/work
choices, capability denial, source revocation, tenant isolation and atomic rollback
after reference creation fails to append its selection decision. Production routes,
converter orchestration and authoritative provider/catalog wiring remain separate.

# Completed application composition

The opt-in authenticated HTTP service, trusted inventory/entitlement configuration,
PostgreSQL discovery management and separate admin/provider delivery receipts are
implemented and exercised locally. The proposal now includes `delivery_receipts`
with deny-client RLS and append-only server grants. See [production composition](production.md)
for API operations and remaining operational prerequisites. No live schema rollout
or production database operation has been performed.
