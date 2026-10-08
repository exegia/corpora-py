---
title: Approved snapshot export and import reconciliation
description: Lossless sidecars, stable-ID synchronization and bounded C-USX rendering.
tags: [references, publication, synchronization]
---

# Approved snapshot contract

The umbrella SnapshotPublicationAdapter implements the core PublicationAdapter
port. Its versioned UTF-8 JSON sidecar carries an authority ID, approved reference
snapshots with matching UUIDs, and optional upstream working versions. It retains
all supported endpoint/locator/provenance data. Unknown schema versions/fields,
invalid models and duplicate IDs reject the whole payload before import planning.
The adapter performs no deployment, network operation or remote publication.

`export_working(store, ids)` selects each requested reference's latest audited
approval and records its working version. Pending/rejected/withdrawn records
reject export. Each entry explicitly pins the selected working revision; selecting
several records is not a database-wide transactional snapshot. The output marks
publication published as an artifact snapshot, while the working database and
history remain unchanged. A later working edit does not alter the earlier artifact.
A future publication ledger must track which artifact versions were distributed.

The generic protocol `export(references, versions=...)` trusts caller-supplied
approved models; it does not authenticate reviewer identity. Use export_working
for audited SQLite snapshots. Versionless portable snapshots remain accepted, but
never establish an ordering against local history. Authority IDs scope upstream
version evidence and do not silently rewrite globally stable reference UUIDs.

# Reconciliation

`plan_import(payload, store)` is read-only. Each entry becomes create, unchanged
or conflict. Compare stable UUID plus source/target/relationship/provenance content;
review/publication/resolution assertions are not imported validation authority.
Identical content is idempotent and leaves local lifecycle/history unchanged.
Conflicting content always needs explicit reconciliation, regardless of whether an
upstream version number looks newer. Numbers from different authorities are not
local compare-and-swap versions. Different UUIDs are not deduplicated by passage
text; their attribution or intent may differ.

`apply_import(decision, store, reason=...)` applies one explicitly chosen entry.
Unknown IDs create the same UUID as an unresolved pending draft and record the
importer, reason, authority and upstream version in local history. Imported approval
or publication flags never confer local approval. Unchanged decisions check the
planned local version/content again. Creation races raise VersionConflictError;
conflicts never overwrite working data. A batch is per-reference, not all-or-nothing;
callers retain payloads/decisions and replan after conflicts. Raw incoming artifacts
should be archived by the production integration for full import provenance.

# Existing C-USX projection

`render_cusx_jump(entry)` emits only an existing USX `char style="jmp"` wrapper
with `link-href=x-corpora:/...` and `link-id=urn:uuid:...` matching the sidecar ID.
It requires a resolved scoped document or structural destination and one pinned
source text selection. UTF-8 URI segments/fragments encode independently; XML
escaping preserves source quote text. Source placement, unique anchor IDs and
published inventory/target advertisement validation remain caller responsibilities.
No insertion into a document or source relocation occurs here.

This helper refuses work-only, text/native/citation destinations instead of
inventing anchors or guessing C-USX selector syntax. Such approved references still
export losslessly in the sidecar. Arbitrary selector embedding, metadata envelopes,
publication anchor bindings and whole-document XML export/import need an agreed
CUSX grammar adapter. The existing graph v0.4 and scoped C-USX contracts remain
unchanged; this helper does not claim complete C-USX or graph conformance.

# Remaining lifecycle work

Publication/withdrawal acknowledgments, distribution history, approved artifact
removal on withdrawal, import conflict resolution UI, authenticated review and
production database adapters remain pending. Conversion rerun idempotency requires
explicit event identity; these rules do not invent one from quote text. No live
Supabase schema or records were changed for this slice.
