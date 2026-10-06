"""New PostgreSQL mapping for a frozen local Corpus Document 0.4.0 snapshot.

No connection or application migration. Text lives in streams/rich blocks once.
"""

import json
import re

SCHEMA = "corpora_draft_040"

# Columns removed from entity properties and mapped into typed tables.
FIELDS = {
    "collections": [("title", "title")],
    "works": [("title", "title")],
    "editions": [
        ("work_id", "workId"),
        ("title", "title"),
        ("language", "language"),
        ("kind", "kind"),
    ],
    "revisions": [
        ("edition_id", "editionId"),
        ("sequence", "sequence"),
        ("previous_revision_id", "previousRevisionId"),
        ("import_id", "importId"),
    ],
    "streams": [("revision_id", "revisionId"), ("ordinal", "order"), ("text", "text")],
    "anchors": [("revision_id", "revisionId")],
    "nodes": [
        ("revision_id", "revisionId"),
        ("node_type", "type"),
        ("anchor_id", "anchorId"),
        ("asset_id", "assetId"),
    ],
    "structures": [("revision_id", "revisionId"), ("name", "name")],
    "profiles": [
        ("version", "version"),
        ("node_types", "nodeTypes"),
        ("feature_keys", "featureKeys"),
        ("required_capabilities", "requiredCapabilities"),
    ],
    "agents": [("name", "name"), ("kind", "kind")],
    "contributions": [("agent_id", "agentId"), ("role", "role")],
    "assets": [("media_type", "mediaType"), ("uri", "uri"), ("sha256", "sha256")],
    "imports": [
        ("adapter", "adapter"),
        ("adapter_version", "adapterVersion"),
        ("agent_id", "agentId"),
        ("report", "report"),
    ],
    "annotations": [("annotation_type", "type"), ("agent_id", "agentId")],
    "schemes": [
        ("name", "name"),
        ("version", "version"),
        ("work_id", "workId"),
        ("edition_id", "editionId"),
        ("revision_id", "revisionId"),
    ],
}
CHILDREN = {
    "collections": ["members"],
    "revisions": ["profileIds"],
    "anchors": ["segments"],
    "nodes": ["position"],
    "structures": ["members"],
    "imports": ["assetIds"],
    "annotations": ["body", "targets"],
    "schemes": ["entries"],
    "contributions": ["target"],
}


def fk(columns, target, target_columns="id"):
    return f"FOREIGN KEY ({columns}) REFERENCES {SCHEMA}.{target} ({target_columns}) DEFERRABLE INITIALLY DEFERRED"


def ddl():
    definitions = {
        "collections": "title text NOT NULL",
        "works": "title text NOT NULL",
        "editions": f"work_id text NOT NULL, title text NOT NULL, language text NOT NULL, kind text NOT NULL, UNIQUE(id,work_id), {fk('work_id', 'works')}",
        "revisions": f"edition_id text NOT NULL, sequence bigint NOT NULL CHECK(sequence>=1), previous_revision_id text, import_id text, UNIQUE(edition_id,sequence), UNIQUE(id,edition_id), {fk('edition_id', 'editions')}, {fk('previous_revision_id,edition_id', 'revisions', 'id,edition_id')}, {fk('import_id', 'imports')}",
        "streams": f"revision_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), text text NOT NULL, UNIQUE(revision_id,ordinal), UNIQUE(id,revision_id), {fk('revision_id', 'revisions')}",
        "anchors": f"revision_id text NOT NULL, UNIQUE(id,revision_id), {fk('revision_id', 'revisions')}",
        "nodes": f"revision_id text NOT NULL, node_type text NOT NULL, anchor_id text, asset_id text, position_stream_id text, position_scalar bigint CHECK(position_scalar>=0), CHECK((position_stream_id IS NULL)=(position_scalar IS NULL)), CHECK(anchor_id IS NULL OR position_stream_id IS NULL), UNIQUE(id,revision_id), {fk('revision_id', 'revisions')}, {fk('anchor_id,revision_id', 'anchors', 'id,revision_id')}, {fk('position_stream_id,revision_id', 'streams', 'id,revision_id')}, {fk('asset_id', 'assets')}",
        "structures": f"revision_id text NOT NULL, name text NOT NULL, UNIQUE(revision_id,name), UNIQUE(id,revision_id), {fk('revision_id', 'revisions')}",
        "profiles": "version text NOT NULL, node_types jsonb NOT NULL, feature_keys jsonb NOT NULL, required_capabilities jsonb NOT NULL",
        "agents": "name text NOT NULL, kind text NOT NULL",
        "contributions": f"agent_id text NOT NULL, role text NOT NULL, target_entity_id text NOT NULL, {fk('agent_id', 'agents')}, {fk('target_entity_id', 'entities')}",
        "assets": "media_type text NOT NULL, uri text NOT NULL, sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$')",
        "imports": f"adapter text NOT NULL, adapter_version text NOT NULL, agent_id text NOT NULL, report jsonb NOT NULL, {fk('agent_id', 'agents')}",
        "annotations": f"annotation_type text NOT NULL, agent_id text NOT NULL, {fk('agent_id', 'agents')}",
        "schemes": f"name text NOT NULL, version text NOT NULL, work_id text NOT NULL, edition_id text NOT NULL, revision_id text NOT NULL, UNIQUE(id,revision_id), {fk('work_id', 'works')}, {fk('edition_id,work_id', 'editions', 'id,work_id')}, {fk('revision_id,edition_id', 'revisions', 'id,edition_id')}",
    }
    statements = [
        "-- PostgreSQL 14+; fresh isolated namespace; no DROP or live database connection.",
        f"CREATE SCHEMA {SCHEMA};",
        f"CREATE TABLE {SCHEMA}.bundles (id text PRIMARY KEY, spec_version text NOT NULL CHECK(spec_version='0.4.0'), required_capabilities jsonb NOT NULL, extensions jsonb NOT NULL, present_tables jsonb NOT NULL, sealed boolean NOT NULL DEFAULT false);",
        f"CREATE TABLE {SCHEMA}.entities (id text PRIMARY KEY, bundle_id text NOT NULL REFERENCES {SCHEMA}.bundles(id), entity_kind text NOT NULL CHECK(entity_kind IN ({','.join(literal(k) for k in FIELDS)})), ordinal bigint NOT NULL CHECK(ordinal>=0), properties jsonb NOT NULL, UNIQUE(id,entity_kind), UNIQUE(bundle_id,entity_kind,ordinal));",
    ]
    for table, definition in definitions.items():
        statements.append(
            f"CREATE TABLE {SCHEMA}.{table} (id text PRIMARY KEY, entity_kind text NOT NULL DEFAULT '{table}' CHECK(entity_kind='{table}'), {definition}, {fk('id,entity_kind', 'entities', 'id,entity_kind')});"
        )
    joins = {
        "source_ids": f"entity_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), asset_id text NOT NULL, value text NOT NULL, PRIMARY KEY(entity_id,ordinal), {fk('entity_id', 'entities')}, {fk('asset_id', 'assets')}",
        "collection_members": f"collection_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), work_id text NOT NULL, edition_id text, PRIMARY KEY(collection_id,ordinal), {fk('collection_id', 'collections')}, {fk('work_id', 'works')}, {fk('edition_id,work_id', 'editions', 'id,work_id')}",
        "revision_profiles": f"revision_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), profile_id text NOT NULL, PRIMARY KEY(revision_id,ordinal), UNIQUE(revision_id,profile_id), {fk('revision_id', 'revisions')}, {fk('profile_id', 'profiles')}",
        "anchor_segments": f"anchor_id text NOT NULL, revision_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), stream_id text NOT NULL, start_scalar bigint NOT NULL CHECK(start_scalar>=0), end_scalar bigint NOT NULL CHECK(end_scalar>start_scalar), PRIMARY KEY(anchor_id,ordinal), {fk('anchor_id,revision_id', 'anchors', 'id,revision_id')}, {fk('stream_id,revision_id', 'streams', 'id,revision_id')}",
        "structure_members": f"structure_id text NOT NULL, revision_id text NOT NULL, node_id text NOT NULL, parent_node_id text, ordinal bigint NOT NULL CHECK(ordinal>=0), member_index bigint NOT NULL CHECK(member_index>=0), PRIMARY KEY(structure_id,node_id), UNIQUE(structure_id,member_index), {fk('structure_id,revision_id', 'structures', 'id,revision_id')}, {fk('node_id,revision_id', 'nodes', 'id,revision_id')}, {fk('structure_id,parent_node_id', 'structure_members', 'structure_id,node_id')}",
        "import_assets": f"import_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), asset_id text NOT NULL, PRIMARY KEY(import_id,ordinal), {fk('import_id', 'imports')}, {fk('asset_id', 'assets')}",
        "annotation_targets": f"annotation_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), entity_id text NOT NULL, PRIMARY KEY(annotation_id,ordinal), {fk('annotation_id', 'annotations')}, {fk('entity_id', 'entities')}",
        "rich_blocks": f"annotation_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), block_type text NOT NULL, text text NOT NULL, marks jsonb NOT NULL, PRIMARY KEY(annotation_id,ordinal), {fk('annotation_id', 'annotations')}",
        "scheme_entries": f"scheme_id text NOT NULL, key text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), PRIMARY KEY(scheme_id,key), UNIQUE(scheme_id,ordinal), {fk('scheme_id', 'schemes')}",
        "reference_bindings": f"scheme_id text NOT NULL, key text NOT NULL, revision_id text NOT NULL, ordinal bigint NOT NULL CHECK(ordinal>=0), node_id text NOT NULL, PRIMARY KEY(scheme_id,key,ordinal), {fk('scheme_id,key', 'scheme_entries', 'scheme_id,key')}, {fk('scheme_id,revision_id', 'schemes', 'id,revision_id')}, {fk('node_id,revision_id', 'nodes', 'id,revision_id')}",
    }
    for table, definition in joins.items():
        statements.append(f"CREATE TABLE {SCHEMA}.{table} ({definition});")
    # Deferred constraints still require referenced tables to exist at CREATE time.
    # Add typed FKs after all typed and join tables have been created.
    foreign_keys = []
    pattern = r", (FOREIGN KEY \([^)]*\) REFERENCES [\w.]+ \([^)]*\) DEFERRABLE INITIALLY DEFERRED)"
    for i, statement in enumerate(statements):
        if not statement.startswith("CREATE TABLE "):
            continue
        table_name = statement.split()[2]
        foreign_keys.extend(
            f"ALTER TABLE {table_name} ADD {match};" for match in re.findall(pattern, statement)
        )
        statements[i] = re.sub(pattern, "", statement)
    statements.extend(foreign_keys)
    statements.extend(
        [
            f"CREATE UNIQUE INDEX structure_root_order ON {SCHEMA}.structure_members(structure_id,ordinal) WHERE parent_node_id IS NULL;",
            f"CREATE UNIQUE INDEX structure_child_order ON {SCHEMA}.structure_members(structure_id,parent_node_id,ordinal) WHERE parent_node_id IS NOT NULL;",
            _VALIDATION.replace("__SCHEMA__", SCHEMA),
            _FREEZE.replace("__SCHEMA__", SCHEMA),
        ]
    )
    for table in ["entities", *definitions, *joins]:
        statements.append(
            f"CREATE TRIGGER snapshot_frozen BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {SCHEMA}.{table} FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.guard_frozen();"
        )
    statements.append(
        f"CREATE TRIGGER bundle_frozen BEFORE INSERT OR UPDATE OR DELETE ON {SCHEMA}.bundles FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.guard_bundle();"
    )
    statements.append(
        f"CREATE TRIGGER bundle_truncate_frozen BEFORE TRUNCATE ON {SCHEMA}.bundles FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.guard_frozen();"
    )
    return "\n\n".join(statements) + "\n"


_VALIDATION = """
CREATE FUNCTION __SCHEMA__.validate_snapshot() RETURNS void LANGUAGE plpgsql AS $corpora_validation$
BEGIN
 IF EXISTS (SELECT 1 FROM __SCHEMA__.entities e JOIN __SCHEMA__.bundles b ON b.id=e.id)
 THEN RAISE EXCEPTION 'Bundle/entity ID collision'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.anchor_segments a JOIN __SCHEMA__.streams s ON s.id=a.stream_id WHERE a.end_scalar>char_length(s.text))
 OR EXISTS (SELECT 1 FROM __SCHEMA__.nodes n JOIN __SCHEMA__.streams s ON s.id=n.position_stream_id WHERE n.position_scalar>char_length(s.text))
 THEN RAISE EXCEPTION 'Scalar bounds violation'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.anchors a WHERE NOT EXISTS (SELECT 1 FROM __SCHEMA__.anchor_segments s WHERE s.anchor_id=a.id))
 THEN RAISE EXCEPTION 'Empty anchor'; END IF;
 IF EXISTS (SELECT 1 FROM (SELECT a.*, s.ordinal AS stream_order, lag(s.ordinal) OVER w AS prior_stream, lag(a.end_scalar) OVER w AS prior_end FROM __SCHEMA__.anchor_segments a JOIN __SCHEMA__.streams s ON s.id=a.stream_id WINDOW w AS (PARTITION BY a.anchor_id ORDER BY a.ordinal)) q WHERE stream_order<prior_stream OR (stream_order=prior_stream AND start_scalar<prior_end))
 THEN RAISE EXCEPTION 'Anchor segment order or overlap'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.revisions r JOIN __SCHEMA__.revisions p ON p.id=r.previous_revision_id WHERE p.sequence>=r.sequence)
 THEN RAISE EXCEPTION 'Invalid predecessor'; END IF;
 IF EXISTS (WITH RECURSIVE walk AS (SELECT structure_id,node_id,parent_node_id,ARRAY[node_id] AS path,false AS cycle FROM __SCHEMA__.structure_members UNION ALL SELECT w.structure_id,w.node_id,m.parent_node_id,w.path||m.node_id,m.node_id=ANY(w.path) FROM walk w JOIN __SCHEMA__.structure_members m ON m.structure_id=w.structure_id AND m.node_id=w.parent_node_id WHERE NOT w.cycle) SELECT 1 FROM walk WHERE cycle)
 THEN RAISE EXCEPTION 'Structure cycle'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.nodes n WHERE n.node_type NOT IN ('core:document','core:section','core:heading','core:paragraph','core:sentence','core:clause','core:word','core:verse','core:page','core:figure','core:milestone') AND NOT EXISTS (SELECT 1 FROM __SCHEMA__.revision_profiles r JOIN __SCHEMA__.profiles p ON p.id=r.profile_id WHERE r.revision_id=n.revision_id AND p.node_types ? n.node_type))
 THEN RAISE EXCEPTION 'Undeclared node type'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.nodes n JOIN __SCHEMA__.entities e ON e.id=n.id CROSS JOIN LATERAL jsonb_object_keys(COALESCE(e.properties->'features','{}'::jsonb)) f(key) WHERE f.key NOT LIKE 'core:%' AND NOT EXISTS (SELECT 1 FROM __SCHEMA__.revision_profiles r JOIN __SCHEMA__.profiles p ON p.id=r.profile_id WHERE r.revision_id=n.revision_id AND p.feature_keys ? f.key))
 THEN RAISE EXCEPTION 'Undeclared feature'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.rich_blocks b CROSS JOIN LATERAL jsonb_array_elements(b.marks) m WHERE (m->>'start')::bigint<0 OR (m->>'end')::bigint<=(m->>'start')::bigint OR (m->>'end')::bigint>char_length(b.text))
 THEN RAISE EXCEPTION 'Annotation mark bounds'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.profiles p CROSS JOIN LATERAL jsonb_array_elements_text(p.required_capabilities) c(value) WHERE c.value NOT IN ('core:text','core:anchors','core:structures','core:references','core:relations','core:annotations','core:positions'))
 THEN RAISE EXCEPTION 'Unsupported required capability'; END IF;
 IF EXISTS (SELECT 1 FROM __SCHEMA__.nodes WHERE position_stream_id IS NOT NULL) AND EXISTS (SELECT 1 FROM __SCHEMA__.bundles WHERE NOT required_capabilities ? 'core:positions')
 THEN RAISE EXCEPTION 'Position capability missing'; END IF;
END;
$corpora_validation$;
"""

_FREEZE = """
CREATE FUNCTION __SCHEMA__.guard_frozen() RETURNS trigger LANGUAGE plpgsql AS $corpora_freeze$
BEGIN
 IF EXISTS (SELECT 1 FROM __SCHEMA__.bundles WHERE sealed) THEN RAISE EXCEPTION 'Frozen snapshot; create a new revision in a new snapshot'; END IF;
 RETURN NULL;
END;
$corpora_freeze$;
CREATE FUNCTION __SCHEMA__.guard_bundle() RETURNS trigger LANGUAGE plpgsql AS $corpora_bundle$
BEGIN
 IF TG_OP <> 'INSERT' AND OLD.sealed THEN RAISE EXCEPTION 'Frozen bundle'; END IF;
 IF TG_OP = 'INSERT' AND EXISTS (SELECT 1 FROM __SCHEMA__.bundles) THEN RAISE EXCEPTION 'One bundle per snapshot namespace'; END IF;
 IF TG_OP = 'UPDATE' AND NEW.sealed THEN PERFORM __SCHEMA__.validate_snapshot(); END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END;
$corpora_bundle$;
"""


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (dict, list)):
        return (
            literal(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
            + "::jsonb"
        )
    if (
        not isinstance(value, str)
        or "\x00" in value
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise ValueError("Unsupported PostgreSQL string value")
    return "'" + value.replace("'", "''") + "'"


def rows(document):
    """Lossless supported subset; refuse nonempty unmapped top-level concepts."""
    unknown = set(document) - {"specVersion", "id", "requiredCapabilities", "extensions", *FIELDS}
    if any(document[k] for k in unknown):
        raise ValueError(f"Unmapped SQL concepts: {sorted(unknown)}")
    out = {
        "bundles": [
            {
                "id": document["id"],
                "spec_version": document["specVersion"],
                "required_capabilities": document["requiredCapabilities"],
                "extensions": document.get("extensions", {}),
                "present_tables": [k for k in FIELDS if k in document],
            }
        ],
        "entities": [],
    }

    def add(table, **values):
        out.setdefault(table, []).append(values)

    for kind, fields in FIELDS.items():
        for ordinal, record in enumerate(document.get(kind, [])):
            props = {
                k: v
                for k, v in record.items()
                if k
                not in {"id", "sourceIds", *[key for _, key in fields], *CHILDREN.get(kind, [])}
            }
            add(
                "entities",
                id=record["id"],
                bundle_id=document["id"],
                entity_kind=kind,
                ordinal=ordinal,
                properties=props,
            )
            values = {column: record.get(key) for column, key in fields}
            if kind == "nodes":
                position = record.get("position", {})
                values.update(
                    position_stream_id=position.get("streamId"),
                    position_scalar=position.get("offset"),
                )
            elif kind == "contributions":
                target = record["target"]
                if (
                    target.get("bundleId", document["id"]) != document["id"]
                    or target["id"] == document["id"]
                ):
                    raise ValueError("External/bundle contribution target outside snapshot subset")
                values["target_entity_id"] = target["id"]
            add(kind, id=record["id"], **values)
            for i, source in enumerate(record.get("sourceIds", [])):
                add(
                    "source_ids",
                    entity_id=record["id"],
                    ordinal=i,
                    asset_id=source["assetId"],
                    value=source["value"],
                )
            if kind == "collections":
                for m in record["members"]:
                    add(
                        "collection_members",
                        collection_id=record["id"],
                        ordinal=m["order"],
                        work_id=m["workId"],
                        edition_id=m.get("editionId"),
                    )
            elif kind == "revisions":
                for i, profile in enumerate(record["profileIds"]):
                    add(
                        "revision_profiles", revision_id=record["id"], ordinal=i, profile_id=profile
                    )
            elif kind == "anchors":
                for i, s in enumerate(record["segments"]):
                    add(
                        "anchor_segments",
                        anchor_id=record["id"],
                        revision_id=record["revisionId"],
                        ordinal=i,
                        stream_id=s["streamId"],
                        start_scalar=s["start"],
                        end_scalar=s["end"],
                    )
            elif kind == "structures":
                for member_index, m in enumerate(record["members"]):
                    add(
                        "structure_members",
                        structure_id=record["id"],
                        revision_id=record["revisionId"],
                        node_id=m["nodeId"],
                        parent_node_id=m.get("parentNodeId"),
                        ordinal=m["order"],
                        member_index=member_index,
                    )
            elif kind == "imports":
                for i, asset in enumerate(record["assetIds"]):
                    add("import_assets", import_id=record["id"], ordinal=i, asset_id=asset)
            elif kind == "annotations":
                for i, target in enumerate(record["targets"]):
                    if target.get("bundleId", document["id"]) != document["id"]:
                        raise ValueError("External annotation endpoint outside snapshot subset")
                    add(
                        "annotation_targets",
                        annotation_id=record["id"],
                        ordinal=i,
                        entity_id=target["id"],
                    )
                for i, b in enumerate(record["body"]):
                    if any("target" in m for m in b.get("marks", [])):
                        raise ValueError("Rich mark endpoints outside snapshot subset")
                    add(
                        "rich_blocks",
                        annotation_id=record["id"],
                        ordinal=i,
                        block_type=b["type"],
                        text=b["text"],
                        marks=b.get("marks", []),
                    )
            elif kind == "schemes":
                for entry in record["entries"]:
                    add(
                        "scheme_entries",
                        scheme_id=record["id"],
                        key=entry["key"],
                        ordinal=entry["order"],
                    )
                    for i, target in enumerate(entry["targetIds"]):
                        add(
                            "reference_bindings",
                            scheme_id=record["id"],
                            key=entry["key"],
                            revision_id=record["revisionId"],
                            ordinal=i,
                            node_id=target,
                        )
    return out


def restore(tables):
    """Reconstruct the logical graph from normalized SQL rows for fidelity checks."""
    bundle = tables["bundles"][0]
    document = {
        "id": bundle["id"],
        "specVersion": bundle["spec_version"],
        "requiredCapabilities": bundle["required_capabilities"],
        "extensions": bundle["extensions"],
        **{k: [] for k in bundle["present_tables"]},
    }
    typed = {k: {r["id"]: r for r in tables.get(k, [])} for k in FIELDS}
    children = {}
    for name, key in [
        ("source_ids", "entity_id"),
        ("collection_members", "collection_id"),
        ("revision_profiles", "revision_id"),
        ("anchor_segments", "anchor_id"),
        ("structure_members", "structure_id"),
        ("import_assets", "import_id"),
        ("annotation_targets", "annotation_id"),
        ("rich_blocks", "annotation_id"),
        ("scheme_entries", "scheme_id"),
    ]:
        grouped = {}
        for r in tables.get(name, []):
            grouped.setdefault(r[key], []).append(r)
        children[name] = grouped
    bindings = {}
    for r in tables.get("reference_bindings", []):
        bindings.setdefault((r["scheme_id"], r["key"]), []).append(r)
    for entity in sorted(tables["entities"], key=lambda r: r["ordinal"]):
        kind, identity = entity["entity_kind"], entity["id"]
        r = {"id": identity, **entity["properties"]}
        for column, key in FIELDS[kind]:
            v = typed[kind][identity][column]
            if v is not None:
                r[key] = v
        source = children["source_ids"].get(identity, [])
        if source:
            r["sourceIds"] = [
                {"assetId": s["asset_id"], "value": s["value"]}
                for s in sorted(source, key=lambda s: s["ordinal"])
            ]

        def group(name, identity=identity):
            return sorted(children[name].get(identity, []), key=lambda x: x["ordinal"])

        if kind == "collections":
            r["members"] = [
                {
                    "workId": m["work_id"],
                    "order": m["ordinal"],
                    **({"editionId": m["edition_id"]} if m["edition_id"] is not None else {}),
                }
                for m in group("collection_members")
            ]
        elif kind == "contributions":
            r["target"] = {"id": typed[kind][identity]["target_entity_id"]}
        elif kind == "revisions":
            r["profileIds"] = [p["profile_id"] for p in group("revision_profiles")]
        elif kind == "anchors":
            r["segments"] = [
                {"streamId": s["stream_id"], "start": s["start_scalar"], "end": s["end_scalar"]}
                for s in group("anchor_segments")
            ]
        elif kind == "nodes" and typed[kind][identity]["position_stream_id"] is not None:
            r["position"] = {
                "streamId": typed[kind][identity]["position_stream_id"],
                "offset": typed[kind][identity]["position_scalar"],
            }
        elif kind == "structures":
            r["members"] = [
                {
                    "nodeId": m["node_id"],
                    "order": m["ordinal"],
                    **(
                        {"parentNodeId": m["parent_node_id"]}
                        if m["parent_node_id"] is not None
                        else {}
                    ),
                }
                for m in sorted(
                    children["structure_members"].get(identity, []), key=lambda m: m["member_index"]
                )
            ]
        elif kind == "imports":
            r["assetIds"] = [a["asset_id"] for a in group("import_assets")]
        elif kind == "annotations":
            r["targets"] = [{"id": t["entity_id"]} for t in group("annotation_targets")]
            r["body"] = [
                {"type": b["block_type"], "text": b["text"], "marks": b["marks"]}
                for b in group("rich_blocks")
            ]
        elif kind == "schemes":
            r["entries"] = [
                {
                    "key": e["key"],
                    "order": e["ordinal"],
                    "targetIds": [
                        b["node_id"]
                        for b in sorted(
                            bindings.get((identity, e["key"]), []), key=lambda b: b["ordinal"]
                        )
                    ],
                }
                for e in group("scheme_entries")
            ]
        document.setdefault(kind, []).append(r)
    return document


def data_sql(tables):
    chunks = [
        "SET LOCAL standard_conforming_strings = on;",
        "SET LOCAL client_encoding = 'UTF8';",
        "SET CONSTRAINTS ALL DEFERRED;",
    ]
    order = [
        "bundles",
        "entities",
        *FIELDS,
        *[k for k in tables if k not in {"bundles", "entities", *FIELDS}],
    ]
    for table in order:
        records = tables.get(table, [])
        for start in range(0, len(records), 200):
            batch = records[start : start + 200]
            columns = list(batch[0])
            if any(list(r) != columns for r in batch):
                raise ValueError("Nonuniform SQL row columns")
            values = ",\n".join("(" + ",".join(literal(r[c]) for c in columns) + ")" for r in batch)
            chunks.append(f"INSERT INTO {SCHEMA}.{table} ({','.join(columns)}) VALUES\n{values};")
    chunks.extend(
        [
            "SET CONSTRAINTS ALL IMMEDIATE;",
            f"SELECT {SCHEMA}.validate_snapshot();",
            f"UPDATE {SCHEMA}.bundles SET sealed=true;",
        ]
    )
    return "\n\n".join(chunks) + "\n"


def validate_declared_rows(create_statements, tables):
    """Static DDL/data check, not a substitute for executing PostgreSQL constraints."""
    from pglast import ast

    catalog, foreign = {}, []

    def names(values):
        return tuple(v.sval for v in values or ())

    def constraint(table, value, column=None):
        kind = value.contype.name
        columns = names(value.keys) or ((column,) if column else ())
        if kind in ("CONSTR_PRIMARY", "CONSTR_UNIQUE"):
            catalog[table]["unique"].append(columns)
            if kind == "CONSTR_PRIMARY":
                catalog[table]["nonnull"].update(columns)
        elif kind == "CONSTR_FOREIGN":
            source = names(value.fk_attrs) or ((column,) if column else ())
            foreign.append((table, source, value.pktable.relname, names(value.pk_attrs)))
        elif kind == "CONSTR_NOTNULL":
            catalog[table]["nonnull"].add(column)
        elif kind == "CONSTR_DEFAULT":
            expression = value.raw_expr
            if not isinstance(expression, ast.A_Const):
                raise ValueError("Nonconstant default outside snapshot validator")
            scalar = expression.val
            catalog[table]["defaults"][column] = (
                scalar.sval
                if isinstance(scalar, ast.String)
                else scalar.boolval
                if isinstance(scalar, ast.Boolean)
                else scalar.ival
            )

    for node in create_statements:
        if isinstance(node, ast.CreateStmt):
            table = node.relation.relname
            catalog[table] = {"columns": {}, "nonnull": set(), "defaults": {}, "unique": []}
            for element in node.tableElts:
                if isinstance(element, ast.ColumnDef):
                    catalog[table]["columns"][element.colname] = names(element.typeName.names)[-1]
                    for value in element.constraints or ():
                        constraint(table, value, element.colname)
                elif isinstance(element, ast.Constraint):
                    constraint(table, element)
        elif isinstance(node, ast.AlterTableStmt):
            for command in node.cmds:
                constraint(node.relation.relname, command.def_)
    expanded = {}
    indexes = {}
    for table, metadata in catalog.items():
        records = []
        for emitted in tables.get(table, []):
            if not set(emitted) <= set(metadata["columns"]):
                raise ValueError("INSERT column absent from declared table")
            row = {**metadata["defaults"], **emitted}
            if any(row.get(c) is None for c in metadata["nonnull"]):
                raise ValueError("Declared NOT NULL violation")
            for column, value in row.items():
                kind = metadata["columns"][column]
                if value is None:
                    continue
                valid = (
                    isinstance(value, str)
                    if kind == "text"
                    else isinstance(value, (dict, list))
                    if kind == "jsonb"
                    else isinstance(value, bool)
                    if kind == "bool"
                    else isinstance(value, int) and not isinstance(value, bool)
                    if kind in ("int8", "bigint")
                    else False
                )
                if not valid:
                    raise ValueError(f"Declared SQL type mismatch: {table}.{column}:{kind}")
            records.append(row)
        expanded[table] = records
        for key in metadata["unique"]:
            values = [tuple(row.get(c) for c in key) for row in records]
            nonnull = [v for v in values if all(x is not None for x in v)]
            if len(nonnull) != len(set(nonnull)):
                raise ValueError("Declared primary/unique key violation")
            indexes[(table, key)] = set(nonnull)
    references = 0
    for table, columns, target, target_columns in foreign:
        if (
            target not in catalog
            or not set(columns) <= set(catalog[table]["columns"])
            or not set(target_columns) <= set(catalog[target]["columns"])
        ):
            raise ValueError("Foreign key references an undeclared column/table")
        if (target, target_columns) not in indexes:
            raise ValueError("Foreign key target is not declared unique")
        for row in expanded[table]:
            value = tuple(row.get(c) for c in columns)
            if any(v is None for v in value):
                continue
            if value not in indexes[(target, target_columns)]:
                raise ValueError(f"Declared FK violation: {table}->{target}")
            references += 1
    return {
        "tables": len(catalog),
        "foreignKeys": len(foreign),
        "foreignKeyValuesChecked": references,
        "uniqueKeys": len(indexes),
        "emittedRows": sum(len(v) for v in expanded.values()),
        "execution": "static parsed DDL/data validation",
    }
