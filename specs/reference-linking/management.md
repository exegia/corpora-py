---
title: Offline working-reference management
description: Versioned storage, validation and review contract for integration adapters.
tags: [references, storage, review]
---

# Working store

`corpora_py.linking_store.SQLiteReferenceStore(path, actor_id=...)` implements the
core ReferenceStore protocol outside the reusable library. It writes only to a
caller-selected local SQLite file. It is an offline reference implementation;
caller-supplied actor identity is trusted and it provides no account authorization.

Each successful write appends a WorkingRevision containing the same reference ID,
monotonic version, actor, UTC time, reason, action, reference snapshot, validation
results and optional conversion evidence. Previous snapshots remain immutable
through this API; it exposes no deletion operation. Database owners can change the
file directly, so this is not a tamper-resistant audit log.

Creation uses `expected_version=None`. Updates require the current positive integer
version. BEGIN IMMEDIATE serializes the check and append in one transaction. A
stale caller raises VersionConflictError without writing. An identical pending-draft
save with unchanged evidence is idempotent after checking the expected version.
Distinct IDs remain distinct even if their text/endpoints are identical.

# Review and resolution

- `save` accepts pending drafts. Edits reopen review; no imported snapshot can
  approve itself or assert publication through this method.
- `resolve_target` records source/target validation, adopts a single resolved target
  only through this explicit action, retains unsuccessful/ambiguous requests, and
  leaves review pending. Prior citation requests remain in history.
- `approve` requires a pending draft and fresh source verification returning the
  current source exactly. The target must also verify exactly; a resolved alternate
  endpoint must first be adopted with resolve_target.
- An explicit reviewer option may approve an unresolved/unavailable external
  citation or whole work with a reason. It cannot override an ambiguous target,
  stale/unavailable physical selection or invalid source. Resolution remains
  separate from approval; the validation report is retained.
- `reject` records a reason on a pending draft. Rejected/approved snapshots must
  be resubmitted as pending before another review transition.

Automatic and manual references use identical validation. Conversion evidence is
retained across lifecycle transitions when the source is unchanged, and cleared
when an edit changes the source unless replacement evidence is supplied. It is
never upgraded into resolver validation. Reference and revision JSON are validated
at boundaries. Resolver implementations supply exact verification authority;
this store does not make a successful resolver trustworthy by itself.

# Remaining production integration

The working database remains authoritative; approved C-USX export is a separate
snapshot operation preserving reference IDs, not a store mutation. The local ledger records publication acknowledgments/withdrawals; the store
performs no distribution or full XML export/import. A future
production adapter needs authenticated actor/ownership checks, RLS, transactional
compare-and-swap/history writes, conversion-report storage and review permissions.
It must use the same conflict/validation tests. Deployments remain separately
scoped and no live database was touched for this slice.

The [snapshot adapter](publication.md) now implements conservative import planning
and per-reference application. The synchronization contract is: match stable IDs and explicit content
versions; identical snapshots are idempotent, conflicting/newer working snapshots
require reconciliation, and imports never confer approval. Rerun conversion must
use an explicit event/idempotency identity rather than deduplicating passage text
or conflating different creators. Local publication/withdrawal history and approved snapshot reconciliation are
implemented. Remote distribution receipts and full XML embedding remain future work.

The [runnable review example](../../packages/linking/examples/review_link.py)
uses separate creator/reviewer adapters against one temporary database. `save`
validates model structure, not external source/target truth; authority comes from
resolver evidence recorded during explicit resolution and approval. Production
clients must not treat unreviewed asserted resolution fields as validation proof.

The [offline Supabase proposal](supabase.md) specifies private storage and server-side
authorization/transaction contracts. Its SQL is a design artifact, not an applied migration.
