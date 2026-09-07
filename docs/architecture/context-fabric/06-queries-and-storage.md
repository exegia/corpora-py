---
title: 06 — Queries and Storage
description: Query patterns, hierarchy-storage evaluation, PostgreSQL DDL (ltree), worked SQL.
type: spec
tags:
  - architecture
  - context-fabric
---

# 06 — Queries and Storage

This document defines the query patterns every Context Fabric server must answer efficiently — ancestry, subtree, adjacency, range, reference resolution, and search — evaluates the candidate storage models for an unlimited-depth ordered hierarchy, commits to **materialized path (Postgres `ltree`) with a `parent_id` adjacency column as the normalized source of truth**, and provides an implementation-ready DDL sketch plus worked SQL for each pattern. The entity shapes stored here are the v1 schemas in [`packages/common/src/common/schemas/context_fabric/v1/`](../../../packages/common/src/common/schemas/context_fabric/v1/common.defs.schema.json); the payloads these queries feed are specified in [05](05-api-payloads.md).

See also: [README](README.md) · [01 Domain Model](01-domain-model.md) · [02 Node Taxonomy](02-node-taxonomy.md) · [03 References](03-references.md) · [04 Physical Location](04-physical-location.md) · [05 API Payloads](05-api-payloads.md) · [07 Migration Mapping](07-migration-mapping.md) · [08 Invariants & Versioning](08-invariants-and-versioning.md)

---

## 1. Query patterns

| # | Pattern | Envelope | Backbone |
|---|---------|----------|----------|
| 1 | Ancestors / breadcrumbs | `NodeResponse.breadcrumbs` | `path @>` (GiST) |
| 2 | Descendants / subtree | `NodeResponse` + `children` | `path <@` + `nlevel` cap |
| 3 | Adjacent reading units (prev/next) | `NodeResponse.prev/next` | keyset on `(edition_id, path)` |
| 4 | Range retrieval | `RangeResponse` | path interval + keyset cursor |
| 5 | Canonical-reference resolution | `ResolveResponse` | walk-down join on partial unique indexes |
| 6 | Corpus search | `SearchResponse` | GIN tsvector + filters |

### 1.1 Ancestors / breadcrumbs

Purpose: the trail above a node (`John → 3` for a verse). Request (illustrative): `GET /v1/editions/{id}/nodes/{id}` — breadcrumbs ship inside every `NodeResponse`. Implementation: one GiST-indexed scan, `path @> :node_path`, ordered by `nlevel(path)` (§4, Q2). No recursion at read time.

### 1.2 Descendants / subtree

Purpose: expand a container (`?expand=children&depth=2`). Implementation: `path <@ :node_path` with `nlevel(path) <= nlevel(:node_path) + :depth` as the depth cap; `ORDER BY path` **is** document order, so the tree reassembles client- or server-side in one pass (§4, Q1). Servers MUST cap depth; beyond the cap, return shallow payloads with `childCount`.

### 1.3 Adjacent reading units (prev/next)

Purpose: verse-to-verse / paragraph-to-paragraph navigation at one level, in document order — across parent boundaries (verse 1 of chapter 4 follows the last verse of chapter 3). Implementation: keyset seek on `(edition_id, path)` filtered by `type`, `LIMIT 1`, forward and reversed (§4, Q3). Never `OFFSET`.

### 1.4 Range retrieval

Purpose: `bible/JHN/3/16` → `bible/JHN/3/21` as a `RangeResponse`. Resolve both endpoint refs to nodes (pattern 5), then select every node at the requested level whose path lies in the document-order interval `[start.path, end of end.path's subtree]`. Pagination is keyset: the opaque `nextCursor` of [05 §1.5](05-api-payloads.md) encodes the last row's `path`; the next page seeks `path > cursor` (§4, Q4/Q5). This supersedes (without breaking) the offset-paginated `GET /storage/{filename}/content` in [`corpus_detail_api.py`](../../../packages/admin/src/admin/services/corpus_detail_api.py) (`{ref, format, passages[], total, offset, limit, next_offset}`).

### 1.5 Canonical-reference resolution

Purpose: `GET /v1/resolve?ref=bible/JHN/3/16` → node ids. Steps:

1. Parse the string into typed segments per the scheme registry ([03](03-references.md)).
2. Normalize each token through the scheme's **alias registry** (`"John"`, `"Jn"`, `"Joh"` → code `JHN`) — labels are never resolution inputs.
3. Walk down: for each segment, an indexed lookup on `(edition_id, type, parent_id, code | ref_ordinal)` — exactly the partial unique indexes in §3, so each hop is a unique-index probe (§4, Q6). Fan out across editions when the ref is edition-unqualified; multiple hits ⇒ `status: "ambiguous"`, a prefix-only match ⇒ `"partial"`.

### 1.6 Corpus search

Purpose: full-text search with structural filters (corpus / work / edition / `type` / `category`). Implementation: GIN-indexed `tsvector` over `text_fragment.text`, per-language configs (§3.3), joined back to `content_node` for filters and to the reference columns for a `ref` per hit; `ts_headline` produces the `<em>…</em>` snippet (§4, Q7). Hits return pointers, not payloads ([05 §1.2](05-api-payloads.md)).

---

## 2. Storage evaluation

Candidates for the node hierarchy, honestly compared:

| Model | Subtree query | Ancestor query | Insert / move cost | Document order | Index footprint | Operational complexity |
|---|---|---|---|---|---|---|
| Adjacency list (`parent_id`) | Recursive CTE, O(depth) iterations | Recursive CTE | O(1) insert, O(1) move | Needs recursive sort or path anyway | Minimal (1 btree) | None — plain SQL |
| **Materialized path (`ltree`)** | **One GiST scan (`<@`)** | **One GiST scan (`@>`)** | O(1) insert at tail; move/insert-middle rewrites subtree paths | **Native — `ORDER BY path`** | Moderate (GiST + btree) | Low — one extension, rebuildable column |
| Closure table | One join on ancestor table | One join | O(depth) rows per insert; expensive move (delete+insert closure rows) | Not provided — needs separate ordering key | Large (O(n·depth) rows + indexes) | Medium — triggers or app discipline to maintain |
| Nested sets (lft/rgt) | Range scan `lft BETWEEN` | Range scan | **O(n) — renumbers on every insert** | Native via `lft` but unstable across inserts | Small | High — fragile renumbering, hostile to concurrency |
| Graph DB (Neo4j etc.) | Native traversal | Native traversal | O(1) | Needs explicit ordering property | n/a | High — second datastore, no Postgres FTS/RLS synergy |

**Decision: materialized path with Postgres `ltree` as the primary access structure, plus a `parent_id` adjacency column as the normalized source of truth.** Paths are derived data, rebuildable from `parent_id` at any time (§5.2).

Rationale:

- **Corpora are effectively immutable after ingest** and the workload is read-dominated. The materialized path's one weakness — subtree path rewrites on move/mid-insert — lands on operations we almost never perform; its strengths land on every request.
- **GiST `<@` / `@>` answers subtree and ancestor queries in one index hop**, no recursion, no closure rows.
- **The path doubles as document order**: `ORDER BY (edition_id, path)` is a btree walk, which gives us prev/next, ranges, and keyset cursors for free.

Fallbacks and rejections:

- **Closure table** is the documented fallback if heavy interactive editing (frequent moves, mid-tree inserts) ever becomes a real workload — O(1)-ish reads survive edits better there. Not built now.
- **Nested sets: rejected.** O(n) renumbering on insert, and document order is not stable across inserts — fatal for append-heavy ingest and for cursor stability.
- **Graph DB: rejected.** A second datastore to operate, secure, and back up, with no synergy with Postgres FTS, RLS, or the rest of the stack. `Relationship` edges ([schema](../../../packages/common/src/common/schemas/context_fabric/v1/relationship.schema.json)) are a typed edge *table* (§3), queried by kind and endpoint — relational is fine; no traversal engine needed.

---

## 3. DDL sketch

Implementation-ready sketch; names are snake_case mirrors of the v1 schema fields. `PhysicalLocator` arrays are the JSONB `locators` column on node and fragment; `ext` is JSONB on every table and is round-tripped untouched.

### 3.1 Catalog tables

```sql
CREATE EXTENSION IF NOT EXISTS ltree;

CREATE TABLE corpus (
  id          uuid PRIMARY KEY,                    -- UUIDv7
  slug        text NOT NULL UNIQUE,
  title       text NOT NULL,
  description text,
  languages   text[],
  publisher   text,
  rights      text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  ext         jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE work (
  id                uuid PRIMARY KEY,
  corpus_id         uuid NOT NULL REFERENCES corpus(id) ON DELETE CASCADE,
  slug              text NOT NULL,
  title             text NOT NULL,
  sort_title        text,
  creators          jsonb,                         -- [{name, role}]
  original_language text,
  genre             text,
  ref_scheme        text,
  date              text,
  ext               jsonb NOT NULL DEFAULT '{}',
  UNIQUE (corpus_id, slug)
);

CREATE TABLE edition (
  id                    uuid PRIMARY KEY,
  work_id               uuid NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  slug                  text NOT NULL,
  title                 text NOT NULL,
  language              text NOT NULL,
  script                text,
  is_translation        boolean NOT NULL DEFAULT false,
  publisher             text,
  date                  text,
  rights                text,
  version               text,                      -- content revision, bumped on re-parse
  supersedes_edition_id uuid REFERENCES edition(id) ON DELETE SET NULL,
  ref_scheme            text,
  structure_profile     jsonb,                     -- {levels:[{levelType,label,addressedBy}]}
  fts_config            regconfig NOT NULL DEFAULT 'simple',  -- per-edition FTS language, see §3.3
  provenance            jsonb,
  ext                   jsonb NOT NULL DEFAULT '{}',
  UNIQUE (work_id, slug)
);

CREATE TABLE source_asset (
  id               uuid PRIMARY KEY,
  edition_id       uuid REFERENCES edition(id) ON DELETE CASCADE,
  source_format    text NOT NULL,                  -- epub | html | xml | tei | pdf | plain | …
  media_type       text,
  uri              text,
  filename         text,
  sha256           text,
  byte_size        bigint,
  page_count       int,
  duration_seconds numeric,
  ext              jsonb NOT NULL DEFAULT '{}'
);
```

### 3.2 The hierarchy: `content_node`

```sql
CREATE TABLE content_node (
  id              uuid PRIMARY KEY,                -- UUIDv7
  edition_id      uuid NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  parent_id       uuid REFERENCES content_node(id) ON DELETE CASCADE,  -- source of truth
  ordinal         int  NOT NULL,                   -- 0-based sibling position
  depth           int  NOT NULL,
  path            ltree NOT NULL,                  -- derived: zero-padded ordinals, e.g. '0001.0003.0016'
  category        text NOT NULL,                   -- frozen v1 enum
  type            text NOT NULL,                   -- open 'ns:name'
  code            text,                            -- code-addressed ref levels ('JHN')
  ref_ordinal     int,                             -- 1-based canonical number (chapter 3)
  label           text,
  heading         text,
  language        text,
  script          text,
  child_count     int  NOT NULL DEFAULT 0,
  source_local_id text,
  locators        jsonb,                           -- PhysicalLocator[]
  provenance      jsonb,
  ext             jsonb NOT NULL DEFAULT '{}',
  CHECK ((parent_id IS NULL) = (depth = 0)),       -- one root per edition
  UNIQUE (edition_id, path),
  UNIQUE (edition_id, parent_id, ordinal)
);

-- Reference resolution: each hop of the walk-down is a unique probe.
CREATE UNIQUE INDEX content_node_refordinal_uq
  ON content_node (edition_id, type, parent_id, ref_ordinal)
  WHERE ref_ordinal IS NOT NULL;
CREATE UNIQUE INDEX content_node_code_uq
  ON content_node (edition_id, type, parent_id, code)
  WHERE code IS NOT NULL;

CREATE INDEX content_node_path_gist    ON content_node USING gist (path);          -- <@ / @>
CREATE INDEX content_node_edition_path ON content_node (edition_id, path);         -- keyset / ranges
CREATE INDEX content_node_parent       ON content_node (parent_id, ordinal);       -- rebuilds, child lists
CREATE INDEX content_node_ext_gin      ON content_node USING gin (ext jsonb_path_ops);
```

The `path` is built from **zero-padded `ordinal`s** (`lpad(ordinal::text, 4, '0')` per level — `0001.0003.0016`), so lexicographic `ltree` order equals document order. Padding width 4 caps siblings at 10 000; widen per deployment if a corpus needs more (§5.1).

### 3.3 Text: `text_fragment`

```sql
CREATE TABLE text_fragment (
  id          uuid PRIMARY KEY,
  node_id     uuid NOT NULL REFERENCES content_node(id) ON DELETE CASCADE,
  edition_id  uuid NOT NULL REFERENCES edition(id) ON DELETE CASCADE,  -- denormalized for filtered FTS
  ordinal     int  NOT NULL,
  text        text NOT NULL,
  after       text NOT NULL DEFAULT '',
  language    text,
  script      text,
  char_start  int,
  char_end    int,
  locators    jsonb,                               -- PhysicalLocator[] (page/bbox/timecodes)
  confidence  real,
  ext         jsonb NOT NULL DEFAULT '{}',
  tsv         tsvector,                            -- maintained by trigger, see below
  UNIQUE (node_id, ordinal)
);

-- Per-language FTS: a GENERATED column only allows a *literal* regconfig
-- (to_tsvector(regconfig-from-a-join, text) is not immutable), so the tsv is
-- maintained by trigger using the owning edition's fts_config:
CREATE FUNCTION text_fragment_tsv() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  SELECT to_tsvector(e.fts_config, NEW.text) INTO NEW.tsv
  FROM edition e WHERE e.id = NEW.edition_id;
  RETURN NEW;
END $$;
CREATE TRIGGER text_fragment_tsv_trg
  BEFORE INSERT OR UPDATE OF text ON text_fragment
  FOR EACH ROW EXECUTE FUNCTION text_fragment_tsv();

CREATE INDEX text_fragment_tsv_gin ON text_fragment USING gin (tsv);
```

**Why fragments are a separate table** (not a `text` column on the node): a node spanning pages carries one fragment per page region, each with its own locator and OCR confidence — that is the join between logical structure and physical carrier; and FTS wants fragment granularity so a hit lands on a page-region-sized snippet, not a whole chapter. Container nodes simply have no rows here.

### 3.4 Standoff and edges

```sql
CREATE TABLE annotation (
  id         uuid PRIMARY KEY,
  edition_id uuid REFERENCES edition(id) ON DELETE CASCADE,
  kind       text NOT NULL,                        -- 'note:footnote', 'ref:crossref', …
  target     jsonb NOT NULL,                       -- {nodeId | fragmentId | range{…}}
  target_node_id     uuid REFERENCES content_node(id)  ON DELETE CASCADE,  -- extracted for joins
  target_fragment_id uuid REFERENCES text_fragment(id) ON DELETE CASCADE,
  body       jsonb,                                -- {text | nodeId | assetId | uri | reference}
  marker     text,
  created_by text,
  created_at timestamptz,
  provenance jsonb,
  ext        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX annotation_node ON annotation (target_node_id);

CREATE TABLE relationship (
  id          uuid PRIMARY KEY,
  kind        text NOT NULL,                       -- 'supersedes', 'aligned-with', 'cites', …
  from_entity text NOT NULL,
  from_id     uuid NOT NULL,
  to_entity   text NOT NULL,
  to_id       uuid NOT NULL,
  confidence  real,
  note        text,
  ext         jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX relationship_from ON relationship (from_entity, from_id, kind);
CREATE INDEX relationship_to   ON relationship (to_entity, to_id, kind);
```

Cascade rules: everything under an edition (`content_node`, `text_fragment`, `source_asset`, `annotation`) cascades on edition delete; `content_node.parent_id` cascades so dropping a subtree root drops the subtree; `relationship` endpoints are polymorphic `(entity, id)` pairs and are garbage-collected by the application, not by FK.

---

## 4. Worked SQL

**Q1 — subtree with depth cap** (descendants of `:p ltree`, pattern 1.2):

```sql
SELECT n.*
FROM content_node n
WHERE n.edition_id = :edition
  AND n.path <@ :p
  AND nlevel(n.path) <= nlevel(:p) + :depth
ORDER BY n.path;                                   -- document order, tree-reassembly ready
```

**Q2 — breadcrumbs** (ancestors of `:p`, outermost first, pattern 1.1):

```sql
SELECT n.id, n.category, n.type, n.label, n.code, n.ref_ordinal
FROM content_node n
WHERE n.edition_id = :edition
  AND n.path @> :p
  AND n.path <> :p
ORDER BY nlevel(n.path);
```

**Q3 — prev/next reading unit** at one level (pattern 1.3; reverse comparison + `DESC` for prev):

```sql
SELECT n.id, n.category, n.type, n.label, n.ref_ordinal
FROM content_node n
WHERE n.edition_id = :edition
  AND n.type = :level_type                         -- e.g. 'bible:verse'
  AND n.path > :current_path                       -- keyset seek, uses (edition_id, path)
ORDER BY n.path
LIMIT 1;
```

**Q4 — range between two resolved endpoints** (pattern 1.4), `:s`/`:e` = start/end node paths:

```sql
SELECT n.*
FROM content_node n
WHERE n.edition_id = :edition
  AND n.type = :level_type
  AND n.path >= :s
  AND (n.path <= :e OR n.path <@ :e)               -- include the end node's subtree
ORDER BY n.path
LIMIT :page_size + 1;                              -- +1 row ⇒ nextCursor exists
```

**Q5 — next page from an opaque cursor** (cursor decodes to the last returned `path`):

```sql
  AND n.path > :cursor_path                        -- replaces "path >= :s" in Q4
```

**Q6 — canonical-reference resolution**, `bible/JHN/3/16` after alias normalization (pattern 1.5); each join is a probe of a §3.2 partial unique index:

```sql
SELECT v.id AS node_id, v.edition_id
FROM content_node b
JOIN content_node c ON c.edition_id = b.edition_id AND c.parent_id = b.id
                   AND c.type = 'bible:chapter' AND c.ref_ordinal = 3
JOIN content_node v ON v.edition_id = c.edition_id AND v.parent_id = c.id
                   AND v.type = 'bible:verse'   AND v.ref_ordinal = 16
WHERE b.edition_id = ANY(:candidate_editions)      -- all editions when unqualified
  AND b.type = 'bible:book' AND b.code = 'JHN';
```

**Q7 — full-text search** with filters, snippet, and ref join-back (pattern 1.6):

```sql
SELECT n.id AS node_id, n.edition_id,
       ts_rank_cd(f.tsv, q)                             AS score,
       ts_headline(e.fts_config, f.text, q,
                   'StartSel=<em>, StopSel=</em>')      AS snippet,
       n.type, n.code, n.ref_ordinal, n.path            -- ref rebuilt from the walk-up
FROM text_fragment f
JOIN content_node n ON n.id = f.node_id
JOIN edition e      ON e.id = f.edition_id,
     websearch_to_tsquery(e.fts_config, :query) q
WHERE f.tsv @@ q
  AND f.edition_id = ANY(:edition_filter)
  AND (:category IS NULL OR n.category = :category)
  AND (:type     IS NULL OR n.type     = :type)
ORDER BY score DESC
LIMIT :page_size + 1;
```

**Q8 — annotations for a subtree** (feeds `?expand=annotations`):

```sql
SELECT a.*
FROM annotation a
JOIN content_node t ON t.id = a.target_node_id
WHERE t.edition_id = :edition AND t.path <@ :p;
```

---

## 5. Operational tradeoffs & notes

### 5.1 `ltree` label constraints

`ltree` labels allow only `[A-Za-z0-9_]` (hyphens are version-dependent) — which is exactly why paths are built from **zero-padded ordinals, never slugs or codes**: `0001.0003.0016` is always a legal label sequence, needs no escaping, and sorts as document order. Semantics (`code`, `ref_ordinal`, `type`) stay in their own columns; the path carries position only. Padding width bounds sibling count (4 ⇒ 10 000); it is a per-deployment constant — changing it means a path rebuild (§5.2), so pick generously at ingest.

### 5.2 Path rebuild procedure

`parent_id` + `ordinal` are the source of truth; `path`, `depth`, and `child_count` are rebuildable in one recursive CTE per edition:

```sql
WITH RECURSIVE t AS (
  SELECT id, lpad(ordinal::text, 4, '0')::ltree AS path, 0 AS depth
  FROM content_node WHERE edition_id = :edition AND parent_id IS NULL
  UNION ALL
  SELECT c.id, t.path || lpad(c.ordinal::text, 4, '0'), t.depth + 1
  FROM content_node c JOIN t ON c.parent_id = t.id
)
UPDATE content_node n SET path = t.path, depth = t.depth
FROM t WHERE n.id = t.id;
```

Run after any structural surgery, padding change, or suspected drift; the `UNIQUE (edition_id, path)` constraint doubles as the integrity check.

### 5.3 Bulk-ingest pattern

Conversion emits whole editions at once (see the job flow in `admin.services`): `COPY` into `content_node`/`text_fragment` with paths precomputed by the converter (it knows the tree; no rebuild needed), **then** create or re-enable the GiST/GIN indexes — building GiST and the tsvector GIN incrementally during a multi-million-row ingest dominates load time. Editions are append-only thereafter; a re-parse is a *new* edition linked by `Relationship(kind: supersedes)`, never an in-place rewrite — which is what keeps the "no moves" assumption of §2 honest.

### 5.4 Supabase fit

This maps directly onto Supabase Postgres: `ltree` is available as an extension; RLS policies gate by corpus visibility (`corpus` gets `owner_id`/`visibility`; `work`→`edition`→`content_node`/`text_fragment` policies check the owning corpus via the FK chain — cheap because every hot table already carries `edition_id`). Note the repo today ships an **offline Text-Fabric sidecar** (`corpora_mcp` + the `/storage` Hub surface) — this DDL is the forward server-side target, not a description of current storage; the phasing from `.corpus` archives to this schema is laid out in [07](07-migration-mapping.md).
