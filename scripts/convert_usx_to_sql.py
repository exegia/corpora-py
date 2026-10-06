"""Full private USX archive -> Corpus Document 0.4.0 -> PostgreSQL snapshot.

Does not connect to a database. All source text outputs must stay under dist/.
"""

import argparse
import hashlib
import json
import re
import stat
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

import check_corpus_document as checker
import corpus_document_sql as sql
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_TAGS = {"usx", "book", "para", "chapter", "verse", "note", "char"}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class Allocations:
    """Opaque random persistent IDs, retained separately from source-local keys."""

    def __init__(self, path, source_sha):
        self.path = path
        self.data = (
            json.loads(path.read_text())
            if path.exists()
            else {"sourceSha256": source_sha, "ids": {}}
        )
        if self.data["sourceSha256"] != source_sha:
            raise ValueError("Allocation manifest belongs to another immutable source")
        ids = list(self.data["ids"].values())
        if len(ids) != len(set(ids)) or any(
            not re.fullmatch(r"urn:corpora-import:[0-9a-f-]{36}", v) for v in ids
        ):
            raise ValueError("Invalid or colliding persistent allocations")

    def get(self, key):
        return self.data["ids"].setdefault(key, "urn:corpora-import:" + str(uuid.uuid4()))

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")


def parse_xml(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entity declarations are unsupported")
    root = etree.fromstring(
        raw,
        etree.XMLParser(
            resolve_entities=False, no_network=True, remove_blank_text=False, strip_cdata=False
        ),
    )
    if (
        any(not isinstance(e.tag, str) for e in root.iter())
        or root.getprevious() is not None
        or root.getnext() is not None
    ):
        raise ValueError("Comments/processing instructions need an explicit preservation mapping")
    return root


def archive_members(path):
    with zipfile.ZipFile(path) as archive:
        seen = set()
        total = 0
        out = []
        for info in archive.infolist():
            member = PurePosixPath(info.filename.replace("\\", "/"))
            if (
                member.is_absolute()
                or ".." in member.parts
                or (member.parts and ":" in member.parts[0])
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ValueError("Unsafe archive member")
            if info.filename in seen or str(member) in seen:
                raise ValueError("Duplicate normalized archive member")
            seen.update((info.filename, str(member)))
            if info.is_dir():
                continue
            total += info.file_size
            if info.file_size > 16 * 1024 * 1024 or total > 256 * 1024 * 1024:
                raise ValueError("Archive exceeds declared resource bounds")
            raw = archive.read(info)
            out.append((info.filename, raw))
        return out


def source_order(members):
    """Use the explicit default publication order; retain ZIP order separately."""
    roots = {name: parse_xml(raw) for name, raw in members if name.endswith(".usx")}
    if not roots:
        raise ValueError("No USX members")
    metadata = [(n, parse_xml(raw)) for n, raw in members if n.endswith("/metadata.xml")]
    language = "und"
    order = list(roots)
    policy = "ZIP central directory order; no canonical order inferred"
    if len(metadata) == 1:
        name, root = metadata[0]
        iso = root.findtext("language/iso")
        if iso and re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*", iso):
            language = iso
        publications = root.findall("publications/publication[@default='true']")
        if len(publications) == 1:
            prefix = name.rsplit("/", 1)[0]
            order = [
                prefix + "/" + e.get("src", "")
                for e in publications[0].findall("structure/content")
            ]
            if len(order) != len(roots) or set(order) != set(roots):
                raise ValueError("Default publication does not cover USX members exactly once")
            policy = "metadata.xml default publication structure/content order"
    if len(order) != len(set(order)):
        raise ValueError("Duplicate publication members")
    return roots, order, language, policy


class Book:
    def __init__(
        self, document, ids, member, root, asset_id, language, agent_id, import_id, profile_id
    ):
        self.document, self.ids, self.member, self.root = document, ids, member, root
        self.asset_id, self.agent_id = asset_id, agent_id
        books = root.findall("book")
        if root.tag != "usx" or root.get("version") != "3.0" or len(books) != 1:
            raise ValueError("Expected observed USX 3.0 envelope with one book")
        self.code = books[0].get("code")
        if not self.code:
            raise ValueError("Missing book source code")
        self.work = self.identity("work")
        self.edition = self.identity("edition")
        self.revision = self.identity("revision")
        self.stream = self.identity("stream")
        self.parts, self.length = [], 0
        self.events, self.xml_members, self.layout, self.spans, self.notes = [], [], [], [], []
        self.open_pairs = {}
        self.chapter = None
        self.verse = None
        self.anchors = {}
        self.span_source = {}
        self.source_count = Counter(e.tag for e in root.iter())
        unknown = set(self.source_count) - SUPPORTED_TAGS
        if unknown:
            raise ValueError(f"Unmapped USX element semantics: {sorted(unknown)}")
        source = [{"assetId": asset_id, "value": self.code}]
        document["works"].append(
            {
                "id": self.work,
                "title": self.code,
                "sourceIds": source,
                "extensions": {
                    "usx:identityStatus": "New local work identity; not reconciled with any canonical catalog"
                },
            }
        )
        document["editions"].append(
            {
                "id": self.edition,
                "workId": self.work,
                "title": self.code + " supplied USX edition",
                "language": language,
                "kind": "edition",
                "sourceIds": source,
            }
        )
        self.revision_record = {
            "id": self.revision,
            "editionId": self.edition,
            "sequence": 1,
            "profileIds": [profile_id],
            "importId": import_id,
            "extensions": {
                "usx:member": member,
                "usx:formatVersion": root.get("version"),
                "usx:rootAttributes": dict(root.attrib),
                "usx:xmlEvents": self.events,
            },
        }
        document["revisions"].append(self.revision_record)

    def identity(self, key):
        return self.ids.get("member/" + self.member + "/" + key)

    def put(self, table, record):
        self.document[table].append(record)
        return record

    def append(self, value, event, field):
        if value is None:
            event[field] = None
            return
        start = self.length
        self.parts.append(value)
        self.length += len(value)
        event[field] = {"streamId": self.stream, "start": start, "end": self.length}

    def node(self, key, kind, start, end, attrs=None, source_value=None):
        record = {
            "id": self.identity(key),
            "revisionId": self.revision,
            "type": kind,
            "extensions": {"usx:attributes": attrs or {}},
            "sourceIds": [{"assetId": self.asset_id, "value": source_value or key}],
        }
        if start < end:
            pair = (start, end)
            if pair not in self.anchors:
                anchor = self.put(
                    "anchors",
                    {
                        "id": self.identity(f"anchor/{len(self.anchors)}"),
                        "revisionId": self.revision,
                        "segments": [{"streamId": self.stream, "start": start, "end": end}],
                    },
                )
                self.anchors[pair] = anchor["id"]
            record["anchorId"] = self.anchors[pair]
        else:
            record["position"] = {"streamId": self.stream, "offset": start}
        return self.put("nodes", record)

    def note(self, element, path, parent_path, sibling):
        identity = self.identity("note/" + path)
        chunks, events, marks = [], [], []
        length = 0

        def add(value, event, field):
            nonlocal length
            if value is None:
                event[field] = None
                return
            start = length
            chunks.append(value)
            length += len(value)
            event[field] = {"annotationId": identity, "block": 0, "start": start, "end": length}

        def walk(e, address, parent, order):
            start = length
            event = {
                "path": address,
                "parent": parent,
                "order": order,
                "tag": e.tag,
                "attributes": dict(e.attrib),
            }
            events.append(event)
            add(e.text, event, "text")
            for i, child in enumerate(e):
                child_event = walk(child, f"{address}/{i}", address, i)
                add(child.tail, child_event, "tail")
            if e.tag == "char" and start < length:
                style = e.get("style", "unknown")
                mark_type = (
                    "usx:" + style
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", style)
                    else "usx:sourceStyle"
                )
                marks.append({"start": start, "end": length, "type": mark_type})
            return event

        walk(element, path, parent_path, sibling)
        target = self.node(
            "xml/" + path, "core:milestone", self.length, self.length, dict(element.attrib), path
        )
        target["extensions"]["usx:xmlPath"] = path
        record = self.put(
            "annotations",
            {
                "id": identity,
                "type": "usx:footnote",
                "agentId": self.agent_id,
                "targets": [{"id": target["id"]}],
                "body": [{"type": "paragraph", "text": "".join(chunks), "marks": marks}],
                "extensions": {
                    "usx:attributes": dict(element.attrib),
                    "usx:xmlEvents": events,
                    "usx:attribution": "Extraction software; historical note authorship unknown",
                },
            },
        )
        self.notes.append(record)
        self.xml_members.append(
            {"nodeId": target["id"], "parentNodeId": self.xml_nodes[parent_path], "order": sibling}
        )
        # Top-level note event is represented in the parent tree by the annotation;
        # note descendants remain in annotation evidence, without text duplication.
        event = {
            "path": path,
            "parent": parent_path,
            "order": sibling,
            "tag": "note",
            "attributes": dict(element.attrib),
            "annotationId": identity,
            "text": None,
        }
        self.events.append(event)
        return event

    def visit(self, element, path="0", parent=None, sibling=0):
        if element.tag == "note":
            if element.get("style") != "f":
                raise ValueError("Non-footnote note needs an explicit reference semantics mapping")
            return self.note(element, path, parent, sibling)
        start = self.length
        attrs = dict(element.attrib)
        tag = element.tag
        event = {"path": path, "parent": parent, "order": sibling, "tag": tag, "attributes": attrs}
        self.events.append(event)
        # Reserve preorder node identity, although its anchor is assigned after traversal.
        node_id = self.identity("xml/" + path)
        self.xml_nodes[path] = node_id
        member = {"nodeId": node_id, "order": sibling}
        if parent is not None:
            member["parentNodeId"] = self.xml_nodes[parent]
        self.xml_members.append(member)
        sid, eid = attrs.get("sid"), attrs.get("eid")
        if tag in ("chapter", "verse"):
            if bool(sid) == bool(eid) or element.text or len(element):
                raise ValueError("Invalid milestone envelope")
            if sid:
                if tag == "chapter" and (self.chapter or self.verse):
                    raise ValueError("Overlapping chapter milestone")
                if tag == "verse" and (not self.chapter or self.verse):
                    raise ValueError("Overlapping verse or verse outside chapter")
                if (tag, sid) in self.open_pairs or (tag, sid) in self.span_source:
                    raise ValueError("Duplicate milestone identity")
                self.open_pairs[(tag, sid)] = (start, len(self.events), attrs, self.chapter)
                if tag == "chapter":
                    self.chapter = sid
                else:
                    self.verse = sid
            else:
                if (tag, eid) not in self.open_pairs:
                    raise ValueError("Unmatched milestone end")
                if tag == "chapter" and self.verse:
                    raise ValueError("Chapter closed with open verse")
                if (self.chapter if tag == "chapter" else self.verse) != eid:
                    raise ValueError("Mismatched milestone pair")
                begin, source_order, opening, chapter = self.open_pairs.pop((tag, eid))
                span = self.node(
                    "span/" + tag + "/" + eid,
                    "core:section" if tag == "chapter" else "core:verse",
                    begin,
                    start,
                    {**opening, "eid": eid},
                    eid,
                )
                self.spans.append((source_order, tag, eid, chapter, span))
                self.span_source[(tag, eid)] = span
                if tag == "chapter":
                    self.chapter = None
                else:
                    self.verse = None
        self.append(element.text, event, "text")
        for i, child in enumerate(element):
            child_event = self.visit(child, f"{path}/{i}", path, i)
            self.append(child.tail, child_event, "tail")
        if tag == "usx":
            kind = "core:document"
        elif tag in ("chapter", "verse"):
            kind = "core:milestone"
        elif tag == "book":
            kind = "usx:bookMetadata"
        elif tag == "char":
            kind = "usx:characterSpan"
        elif tag == "para":
            style = attrs.get("style", "")
            kind = (
                "usx:poetryLine"
                if style.startswith("q")
                else "core:heading"
                if style in {"h", "toc1", "toc2", "toc3", "mt", "mt1", "mt2"}
                else "core:paragraph"
            )
        else:
            raise ValueError("Unhandled element")
        node = self.node("xml/" + path, kind, start, self.length, attrs, path)
        node["extensions"]["usx:xmlPath"] = path
        if tag == "para":
            self.layout.append((len(self.events), node))
        return event

    def convert(self):
        self.xml_nodes = {}
        self.visit(self.root)
        self.events[0]["tail"] = None
        if self.open_pairs or self.chapter or self.verse:
            raise ValueError("Unclosed chapter/verse milestone")
        text = "".join(self.parts)
        self.put(
            "streams",
            {
                "id": self.stream,
                "revisionId": self.revision,
                "order": 0,
                "text": text,
                "extensions": {
                    "usx:textPolicy": "All XML-decoded non-note character data, including formatting whitespace and book metadata; no normalization or separators"
                },
            },
        )
        scripture = [{"nodeId": self.xml_nodes["0"], "order": 0}]
        entries = []
        chapter_order = 0
        verse_orders = Counter()
        for i, (_, tag, key, chapter, node) in enumerate(sorted(self.spans)):
            parent = (
                self.xml_nodes["0"]
                if tag == "chapter"
                else self.span_source[("chapter", chapter)]["id"]
            )
            order = chapter_order if tag == "chapter" else verse_orders[chapter]
            if tag == "chapter":
                chapter_order += 1
            else:
                verse_orders[chapter] += 1
            scripture.append({"nodeId": node["id"], "parentNodeId": parent, "order": order})
            entries.append({"key": key, "order": i, "targetIds": [node["id"]]})
        for name, members in [
            ("usx:xmlTree", self.xml_members),
            ("usx:scripture", scripture),
            (
                "usx:layout",
                [{"nodeId": n["id"], "order": i} for i, (_, n) in enumerate(self.layout)],
            ),
        ]:
            self.put(
                "structures",
                {
                    "id": self.identity("structure/" + name),
                    "revisionId": self.revision,
                    "name": name,
                    "members": members,
                },
            )
        self.put(
            "schemes",
            {
                "id": self.identity("scheme"),
                "name": "usx:sourceAddress",
                "version": "1.0.0",
                "workId": self.work,
                "editionId": self.edition,
                "revisionId": self.revision,
                "entries": entries,
            },
        )
        reconstructed = reconstruct_xml(self.document, self.revision_record)
        if not xml_equal(self.root, reconstructed):
            raise ValueError("Decoded XML infoset fidelity failure")
        expected = outside_note_text(self.root)
        if expected != text:
            raise ValueError("Independent text traversal mismatch")
        para = [n for _, n in self.layout]
        by_anchor = {a["id"]: a["segments"][0] for a in self.document["anchors"]}
        crossing = 0
        for _, tag, _, _, node in self.spans:
            if tag != "verse" or "anchorId" not in node:
                continue
            v = by_anchor[node["anchorId"]]
            crossing += (
                sum(
                    p.get("anchorId") is not None
                    and by_anchor[p["anchorId"]]["start"] < v["end"]
                    and v["start"] < by_anchor[p["anchorId"]]["end"]
                    for p in para
                )
                > 1
            )
        pairs = Counter(tag for _, tag, _, _, _ in self.spans)
        if (
            self.source_count["chapter"] != 2 * pairs["chapter"]
            or self.source_count["verse"] != 2 * pairs["verse"]
            or self.source_count["note"] != len(self.notes)
        ):
            raise ValueError("Source count reconciliation failed")
        return {
            "bookCode": self.code,
            "member": self.member,
            "sourceVersion": self.root.get("version"),
            "chapters": pairs["chapter"],
            "verses": pairs["verse"],
            "notes": len(self.notes),
            "paragraphs": self.source_count["para"],
            "characters": self.source_count["char"],
            "streamScalars": len(text),
            "noteScalars": sum(len(n["body"][0]["text"]) for n in self.notes),
            "sourceElements": dict(self.source_count),
            "versesCrossingParagraphs": crossing,
            "decodedXmlRoundTripExact": True,
            "nonNoteTextExact": True,
            "streamSha256": digest(text.encode("utf-8")),
        }


def outside_note_text(root):
    def pieces(e):
        if e.tag == "note":
            return
        yield e.text or ""
        for c in e:
            yield from pieces(c)
            yield c.tail or ""

    return "".join(pieces(root))


def xml_equal(a, b):
    return (
        a.tag == b.tag
        and dict(a.attrib) == dict(b.attrib)
        and a.text == b.text
        and a.tail == b.tail
        and len(a) == len(b)
        and all(xml_equal(x, y) for x, y in zip(a, b, strict=True))
    )


def reconstruct_xml(document, revision):
    streams = {s["id"]: s["text"] for s in document["streams"]}
    annotations = {a["id"]: a for a in document["annotations"]}

    def value(location):
        if location is None:
            return None
        text = (
            streams[location["streamId"]]
            if "streamId" in location
            else annotations[location["annotationId"]]["body"][location["block"]]["text"]
        )
        return text[location["start"] : location["end"]]

    def tree(events):
        nodes = {}
        root = None
        for event in events:
            if "annotationId" in event:
                node = tree(annotations[event["annotationId"]]["extensions"]["usx:xmlEvents"])
            else:
                node = etree.Element(event["tag"], event["attributes"])
                node.text = value(event.get("text"))
            node.tail = value(event.get("tail"))
            nodes[event["path"]] = node
            if event["parent"] in nodes:
                nodes[event["parent"]].append(node)
            elif root is None:
                root = node
            else:
                raise ValueError("Disconnected XML evidence")
        return root

    return tree(revision["extensions"]["usx:xmlEvents"])


def convert(source, output):
    output = output.resolve()
    if ROOT / "dist" not in output.parents:
        raise ValueError("Private artifacts must be in this checkout's ignored dist/ directory")
    output.mkdir(parents=True, exist_ok=True)
    before = (digest(source.read_bytes()), source.stat().st_mtime_ns)
    ids = Allocations(output / "identity-allocations.json", before[0])
    members = archive_members(source)
    roots, order, language, policy = source_order(members)
    document = {
        "specVersion": "0.4.0",
        "id": ids.get("bundle"),
        "requiredCapabilities": [
            "core:text",
            "core:anchors",
            "core:structures",
            "core:positions",
            "core:annotations",
            "core:references",
        ],
        "extensions": {
            "usx:sourceSha256": before[0],
            "usx:collectionOrderPolicy": policy,
            "usx:zipMemberOrder": [name for name, _ in members],
        },
        **{k: [] for k in sql.FIELDS},
    }
    agent = ids.get("agent")
    profile = ids.get("profile")
    import_id = ids.get("import")
    archive_id = ids.get("asset/archive")
    document["agents"].append(
        {"id": agent, "kind": "software", "name": "Corpora full-archive USX SQL converter 0.1.0"}
    )
    document["profiles"].append(
        {
            "id": profile,
            "version": "0.1.0",
            "nodeTypes": ["usx:bookMetadata", "usx:characterSpan", "usx:poetryLine"],
            "featureKeys": [],
            "requiredCapabilities": ["core:positions", "core:annotations", "core:references"],
        }
    )
    rights = "Private local conversion; consult the unchanged source license.xml; no redistribution permission inferred"
    document["assets"].append(
        {
            "id": archive_id,
            "mediaType": "application/zip",
            "uri": source.as_uri(),
            "sha256": before[0],
            "rights": rights,
        }
    )
    assets, manifest = {}, []
    for ordinal, (name, raw) in enumerate(members):
        identity = ids.get("asset/member/" + name)
        assets[name] = identity
        media = (
            "application/vnd.usx+xml"
            if name.endswith(".usx")
            else "application/xml"
            if name.endswith((".xml", ".ldml"))
            else "text/plain"
        )
        document["assets"].append(
            {
                "id": identity,
                "mediaType": media,
                "uri": "zip-member:" + archive_id + "!/" + name,
                "sha256": digest(raw),
                "rights": rights,
                "extensions": {"usx:member": name, "usx:zipOrder": ordinal, "usx:bytes": len(raw)},
            }
        )
        manifest.append(
            {
                "member": name,
                "sha256": digest(raw),
                "bytes": len(raw),
                "convertedUsx": name in roots,
            }
        )
    document["imports"].append(
        {
            "id": import_id,
            "assetIds": [archive_id, *assets.values()],
            "adapter": "full-archive-usx-sql-experiment",
            "adapterVersion": "0.1.0",
            "agentId": agent,
            "report": [
                {
                    "aspect": "USX decoded infoset",
                    "status": "preserved",
                    "detail": "All USX elements/attributes/text/tails verified through source evidence round trip; note text stored only in annotations",
                },
                {
                    "aspect": "source bytes",
                    "status": "transformed",
                    "detail": "XML line-ending/entity normalization is unavoidable; original bytes referenced by checksum, not regenerated",
                },
                {
                    "aspect": "auxiliary members",
                    "status": "unsupported",
                    "detail": "Metadata supplies language and publication order; all auxiliary members retained as provenance assets. License, styles, collation and versification semantics are not promoted to core claims",
                },
                {
                    "aspect": "authorship/catalog",
                    "status": "unsupported",
                    "detail": "Local book work identities; no historical author, translator or canonical catalog equivalence inferred",
                },
            ],
        }
    )
    books = []
    collection = {
        "id": ids.get("collection"),
        "title": source.stem + " supplied USX collection",
        "members": [],
    }
    document["collections"].append(collection)
    for i, member in enumerate(order):
        book = Book(
            document,
            ids,
            member,
            roots[member],
            assets[member],
            language,
            agent,
            import_id,
            profile,
        )
        books.append(book.convert())
        collection["members"].append({"workId": book.work, "editionId": book.edition, "order": i})
    if len({b["bookCode"] for b in books}) != len(books):
        raise ValueError("Duplicate source book codes")
    print(f"Converted {len(books)} complete books; checking graph", flush=True)
    errors = checker.validate(document)
    if errors:
        raise ValueError("Draft conformance failure: " + str(errors[:5]))
    tables = sql.rows(document)
    restored = sql.restore(tables)
    if restored != document:
        raise ValueError("Normalized relational round trip changed document")
    for revision, member in zip(restored["revisions"], order, strict=True):
        if not xml_equal(roots[member], reconstruct_xml(restored, revision)):
            raise ValueError("Relational source round trip failed")
    ddl = sql.ddl()
    data = sql.data_sql(tables)
    combined = (
        "-- PRIVATE source-derived content; PostgreSQL 14+; fresh disposable database only.\nBEGIN;\nSET LOCAL standard_conforming_strings=on;\nSET LOCAL client_encoding='UTF8';\n"
        + ddl
        + data
        + "COMMIT;\n"
    )
    syntax = validate_sql(combined, tables)
    validate_sql(QUERIES, {})
    syntax["representativeQueriesParsed"] = True
    after = (digest(source.read_bytes()), source.stat().st_mtime_ns)
    if before != after:
        raise ValueError("Source ZIP changed during conversion")
    ids.save()
    (output / "corpus-document.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "schema.sql").write_text("BEGIN;\n" + ddl + "COMMIT;\n")
    (output / "data.sql").write_text("BEGIN;\n" + data + "COMMIT;\n")
    (output / "import.sql").write_text(combined)
    (output / "queries.sql").write_text(QUERIES)
    requirements = ROOT / "scripts/usx_sql_requirements.txt"
    (output / "requirements.txt").write_text(requirements.read_text())
    totals = {
        k: sum(b[k] for b in books)
        for k in (
            "chapters",
            "verses",
            "notes",
            "paragraphs",
            "characters",
            "streamScalars",
            "noteScalars",
            "versesCrossingParagraphs",
        )
    }
    from importlib.metadata import version

    report = {
        "status": "converted-and-statically-validated",
        "dialect": "PostgreSQL 14+",
        "specVersion": "0.4.0",
        "converterVersion": "0.1.0",
        "implementationHashes": {
            name: digest((ROOT / "scripts" / name).read_bytes())
            for name in (
                "convert_usx_to_sql.py",
                "corpus_document_sql.py",
                "check_corpus_document.py",
                "usx_sql_requirements.txt",
            )
        },
        "dependencyVersions": {name: version(name) for name in ("lxml", "jsonschema", "pglast")},
        "sourceSha256": before[0],
        "originalChecksumAndMtimeUnchanged": True,
        "usxMembersConverted": len(books),
        "auxiliaryMembers": len(members) - len(books),
        "language": language,
        "orderPolicy": policy,
        "totals": totals,
        "books": books,
        "assets": manifest,
        "entityCounts": {
            k: len(v)
            for k, v in document.items()
            if isinstance(v, list) and k != "requiredCapabilities"
        },
        "sqlRowCounts": {k: len(v) for k, v in tables.items()},
        "draftShapeAndGraphValidated": True,
        "normalizedRelationalRoundTripExact": True,
        "allDecodedXmlRoundTripsExact": True,
        "postgresqlSyntax": syntax,
        "postgresqlExecution": "unavailable: no existing disposable PostgreSQL runtime; no live connection attempted",
        "upstreamUsxSchemaValidated": False,
        "relations": "No structured cross-reference elements in this archive; no invented relations or resolution outcomes",
        "limits": [
            "New snapshot mapping implements the concepts present in this source; refuses nonempty unmapped concepts such as relations/contributions/resolutions rather than silently dropping them",
            "XML lexical bytes are not reconstructed; the complete decoded element/attribute/text/tail infoset is reconstructed exactly",
            "Unknown source semantics remain namespaced evidence; auxiliary license/styles/versification semantics remain source assets",
            "Database runtime constraints and SQL query results are unverified; representative results are independently computed from the normalized rows",
            "Immutable local snapshot schema; no production RLS/API/migration/catalog reconciliation",
        ],
        "artifacts": {
            n: digest((output / n).read_bytes())
            for n in (
                "corpus-document.json",
                "schema.sql",
                "data.sql",
                "import.sql",
                "queries.sql",
                "identity-allocations.json",
                "requirements.txt",
            )
        },
    }
    report["representativeResults"] = representative(tables, document)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "README.md").write_text(readme(report))
    (output / "report.md").write_text(report_markdown(report))
    print(
        f"PASS: {len(books)} books; {totals['chapters']} chapters; {totals['verses']} verses; {totals['notes']} notes",
        flush=True,
    )
    print(
        "PASS: draft graph, decoded XML, text coverage, normalized rows, parsed SQL row round trip; source unchanged",
        flush=True,
    )
    print(output, flush=True)
    return report


def validate_sql(script, expected):
    """PostgreSQL parser round trip: every generated INSERT value, not just grammar."""
    from importlib.metadata import version

    from pglast import ast, parse_plpgsql, parse_sql, split

    actual = {}

    def scalar(node):
        if isinstance(node, ast.TypeCast):
            return json.loads(scalar(node.arg))
        if not isinstance(node, ast.A_Const):
            raise ValueError("Unexpected generated SQL value")
        if node.isnull:
            return None
        if isinstance(node.val, ast.String):
            return node.val.sval
        if isinstance(node.val, ast.Integer):
            return node.val.ival
        if isinstance(node.val, ast.Boolean):
            return node.val.boolval
        raise ValueError("Unexpected generated SQL scalar")

    # pglast's Unicode AST locations are expensive on an entire large script.
    # PostgreSQL's scanner splits only at actual statement boundaries, including
    # quoted strings/function bodies; each complete statement is then parsed.
    statements = split(script, with_parser=False, only_slices=True)
    functions = 0
    declarations = []
    for section in statements:
        statement = script[section]
        for raw in parse_sql(statement):
            node = raw.stmt
            if isinstance(node, (ast.CreateStmt, ast.AlterTableStmt)):
                declarations.append(node)
            if isinstance(node, ast.CreateFunctionStmt):
                parse_plpgsql(statement)
                functions += 1
            if isinstance(node, ast.InsertStmt):
                if node.relation.schemaname != sql.SCHEMA:
                    raise ValueError("SQL escaped intended schema")
                columns = [c.name for c in node.cols]
                for values in node.selectStmt.valuesLists:
                    actual.setdefault(node.relation.relname, []).append(
                        dict(zip(columns, map(scalar, values), strict=True))
                    )
    expected = {k: v for k, v in expected.items() if v}
    if actual != expected:
        raise ValueError("SQL parsed row reconstruction differs from validated rows")
    declared_rows = sql.validate_declared_rows(declarations, actual)
    return {
        "validator": "pglast",
        "version": version("pglast"),
        "statements": len(statements),
        "allInsertRowsExact": True,
        "plpgsqlFunctionsParsed": functions,
        "declaredRowIntegrity": declared_rows,
    }


def representative(tables, document):
    nodes = {r["id"]: r for r in tables["nodes"]}
    anchors = {r["anchor_id"]: r for r in tables["anchor_segments"]}
    schemes = {r["id"]: r for r in tables["schemes"]}
    binding = next(r for r in tables["reference_bindings"] if r["key"] == "LUK 1:1")
    target = nodes[binding["node_id"]]
    span = anchors[target["anchor_id"]]
    texts = {r["id"]: r["text"] for r in tables["streams"]}
    body = texts[span["stream_id"]][span["start_scalar"] : span["end_scalar"]]
    layout_ids = {
        r["id"]
        for r in tables["structures"]
        if r["name"] == "usx:layout" and r["revision_id"] == target["revision_id"]
    }
    overlaps = sum(
        1
        for m in tables["structure_members"]
        if m["structure_id"] in layout_ids
        and nodes[m["node_id"]]["anchor_id"] is not None
        and anchors[nodes[m["node_id"]]["anchor_id"]]["start_scalar"] < span["end_scalar"]
        and span["start_scalar"] < anchors[nodes[m["node_id"]]["anchor_id"]]["end_scalar"]
    )
    revision = schemes[binding["scheme_id"]]["revision_id"]
    note_targets = {n["id"] for n in tables["nodes"] if n["revision_id"] == revision}
    note_ids = {
        t["annotation_id"] for t in tables["annotation_targets"] if t["entity_id"] in note_targets
    }
    chapter_binding = next(r for r in tables["reference_bindings"] if r["key"] == "LUK 1")
    chapter_span = anchors[nodes[chapter_binding["node_id"]]["anchor_id"]]
    chapter_text = texts[chapter_span["stream_id"]][
        chapter_span["start_scalar"] : chapter_span["end_scalar"]
    ]
    chapter_notes = sum(
        1
        for t in tables["annotation_targets"]
        if nodes[t["entity_id"]]["position_stream_id"] == chapter_span["stream_id"]
        and chapter_span["start_scalar"]
        <= nodes[t["entity_id"]]["position_scalar"]
        < chapter_span["end_scalar"]
    )
    crossing_example = None
    for b in tables["reference_bindings"]:
        if not b["key"].startswith("LUK 1:"):
            continue
        v = anchors[nodes[b["node_id"]]["anchor_id"]]
        count = sum(
            1
            for m in tables["structure_members"]
            if m["structure_id"] in layout_ids
            and nodes[m["node_id"]]["anchor_id"] is not None
            and anchors[nodes[m["node_id"]]["anchor_id"]]["start_scalar"] < v["end_scalar"]
            and v["start_scalar"] < anchors[nodes[m["node_id"]]["anchor_id"]]["end_scalar"]
        )
        if count > 1:
            crossing_example = {"key": b["key"], "overlappingLayoutNodes": count}
            break
    return {
        "execution": "computed from normalized validated rows; SQL queries supplied but not executed",
        "bookList": [w["title"] for w in document["works"]],
        "LUK_1_1": {
            "matchedNodes": 1,
            "scalars": len(body),
            "sha256": digest(body.encode("utf-8")),
            "overlappingLayoutNodes": overlaps,
        },
        "LUK_notes": len(note_ids),
        "LUK_1": {
            "scalars": len(chapter_text),
            "sha256": digest(chapter_text.encode("utf-8")),
            "notes": chapter_notes,
        },
        "overlapExample": crossing_example,
        "allNotes": len(tables["annotations"]),
    }


QUERIES = """-- PostgreSQL queries; read results after importing into an isolated database.
-- 1. Source publication order and book list.
SELECT m.ordinal,w.title AS source_book_code,e.language
FROM corpora_draft_040.collection_members m
JOIN corpora_draft_040.works w ON w.id=m.work_id
JOIN corpora_draft_040.editions e ON e.id=m.edition_id ORDER BY m.ordinal;

-- 2. Exact source-bound passage; scalar offsets are zero-based, PostgreSQL substring is one-based.
SELECT b.key, string_agg(substring(t.text FROM a.start_scalar::integer+1 FOR (a.end_scalar-a.start_scalar)::integer),'' ORDER BY a.ordinal) AS text
FROM corpora_draft_040.reference_bindings b
JOIN corpora_draft_040.nodes n ON n.id=b.node_id
JOIN corpora_draft_040.anchor_segments a ON a.anchor_id=n.anchor_id
JOIN corpora_draft_040.streams t ON t.id=a.stream_id
WHERE b.key='LUK 1:1' GROUP BY b.scheme_id,b.key;

-- 3. Notes attached to positions within Luke chapter 1 (body text returned only on request).
SELECT count(*) AS note_count
FROM corpora_draft_040.annotations x
JOIN corpora_draft_040.annotation_targets q ON q.annotation_id=x.id
JOIN corpora_draft_040.nodes p ON p.id=q.entity_id
JOIN corpora_draft_040.reference_bindings b ON b.key='LUK 1'
JOIN corpora_draft_040.nodes c ON c.id=b.node_id
JOIN corpora_draft_040.anchor_segments a ON a.anchor_id=c.anchor_id
WHERE p.position_stream_id=a.stream_id AND p.position_scalar>=a.start_scalar AND p.position_scalar<a.end_scalar;

-- 4. Verse/layout overlap; structures remain independent rather than forcing a single tree.
SELECT b.key,count(*) AS layout_blocks
FROM corpora_draft_040.reference_bindings b
JOIN corpora_draft_040.nodes v ON v.id=b.node_id AND v.node_type='core:verse'
JOIN corpora_draft_040.anchor_segments va ON va.anchor_id=v.anchor_id
JOIN corpora_draft_040.structures s ON s.revision_id=v.revision_id AND s.name='usx:layout'
JOIN corpora_draft_040.structure_members m ON m.structure_id=s.id
JOIN corpora_draft_040.nodes p ON p.id=m.node_id
JOIN corpora_draft_040.anchor_segments pa ON pa.anchor_id=p.anchor_id AND pa.stream_id=va.stream_id AND pa.start_scalar<va.end_scalar AND va.start_scalar<pa.end_scalar
GROUP BY b.scheme_id,b.key HAVING count(*)>1 ORDER BY b.key;
"""


def readme(report):
    return f"""# Private full-archive USX SQL conversion

Dialect: **PostgreSQL 14+**, UTF-8. Draft semantic contract: **0.4.0**.
Source SHA-256: `{report["sourceSha256"]}`. Original ZIP unchanged.

`import.sql` combines DDL and all data in one BEGIN/COMMIT transaction.
`schema.sql` and `data.sql` are equivalent separately transaction-wrapped stages.
Use **either** combined import **or** schema followed by data, never both.
No connection has been made to a database. No system database was installed.

After independently creating a fresh disposable database, the commands are:

```sh
psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname "$DISPOSABLE_DATABASE_URL" --file import.sql
psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname "$DISPOSABLE_DATABASE_URL" --file queries.sql
```

Do not supply a production/Supabase database URL. The script creates a fresh
`corpora_draft_040` schema, fails on an existing namespace, has no DROP, and seals
the complete snapshot against later writes. A failed statement rolls back the
combined transaction. This is a local relational mapping, not a migration.

Opaque random URNs are persistently retained in `identity-allocations.json`.
Keep that file for replay; IDs are not hashes of source IDs/citations/offsets.
Replay to the same output directory reuses IDs and must reproduce every artifact.

`corpus-document.json` is the validated intermediate. Entity common/unknown
properties are stored in `entities.properties`; mapped fields and children are
removed from that JSON and stored in typed tables/joins. Manuscript text appears
once in streams; notes appear once in rich blocks. Anchors share stored streams.
Source evidence references text ranges, preserving XML text/tails without copying
the same text into each node. Profiles/import attribution/assets/reference schemes
have typed joins. Independent XML, scripture and layout structures retain overlap.
The default publication order is explicit in source metadata, not ZIP/citation sort.

The schema implements the concepts actually present in this archive. Relations,
contributions, external endpoints and resolution outcomes are absent; nonempty
unmapped concepts are refused. This is not a complete universal relational codec.
The original license, styles, LDML and versification remain checksum-addressed
provenance assets. Their semantics are not silently asserted as core facts.

All {report["usxMembersConverted"]} USX files are converted. Exact XML decoded
element/attribute/text/tail round trips and full counts were checked. This does not
prove official USX XSD conformance or byte-for-byte XML reconstruction. XML parsing
normalizes line endings/entities; immutable original bytes remain in the ZIP.

`report.json` contains counts/hashes/results; `report.md` is the readable report.
SQL grammar and every parsed INSERT value were checked with pglast.
Declared SQL column types, NOT NULL, primary/unique keys and all emitted foreign
key values were checked statically against the parsed DDL. PL/pgSQL function
bodies were parsed. Snapshot write guards include TRUNCATE. These checks cover
the generated dataset and do not substitute for PostgreSQL execution.
Actual PostgreSQL execution and constraint behavior remain unverified because no existing
disposable runtime is available. Query results in the report are computed from
validated normalized rows and clearly labelled accordingly.

Everything in this directory is PRIVATE source-derived content. Do not add it
to the portable specification bundle or publish it. No RLS/API deployment is supplied.
"""


def report_markdown(report):
    t = report["totals"]
    table = "\n".join(
        f"| {b['bookCode']} | {b['chapters']} | {b['verses']} | {b['notes']} | {b['paragraphs']} | {b['versesCrossingParagraphs']} |"
        for b in report["books"]
    )
    return f"""# Full USX → Corpus Document 0.4.0 → PostgreSQL report

Status: **converted and statically validated; PostgreSQL execution unverified**.
Coverage: **{report["usxMembersConverted"]} of {report["usxMembersConverted"]} USX members**;
{t["chapters"]} chapters, {t["verses"]} verses, {t["notes"]} footnotes,
{t["paragraphs"]} paragraphs, {t["characters"]} note character spans.
{t["streamScalars"]:,} non-note stream scalars and {t["noteScalars"]:,} note scalars.
{t["versesCrossingParagraphs"]} verses overlap multiple source paragraph blocks.

Original checksum and mtime unchanged. All chapter/verse starts paired with ends.
All source note/paragraph/character counts matched; no truncation or invented data.
All decoded XML infosets reconstructed exactly, including text/tails/attributes/order.
All normalized SQL rows reconstructed the same draft document. PostgreSQL parser
checked {report["postgresqlSyntax"]["statements"]} statements and every INSERT value.
Static declared row integrity: {report["postgresqlSyntax"]["declaredRowIntegrity"]["tables"]}
tables, {report["postgresqlSyntax"]["declaredRowIntegrity"]["foreignKeys"]} foreign keys,
{report["postgresqlSyntax"]["declaredRowIntegrity"]["foreignKeyValuesChecked"]:,} non-null
foreign-key values; all passed. Three PL/pgSQL functions and all four example queries parsed.

Publication order: `{report["orderPolicy"]}`. Language: `{report["language"]}`.
No structured cross-reference elements are present; no relations were invented.
Private note authorship remains unknown; extraction attribution names the software.

| Book | Chapters | Verses | Notes | Paragraphs | Verses crossing paragraphs |
| --- | ---: | ---: | ---: | ---: | ---: |
{table}

Representative normalized-row results (not executed PostgreSQL results):

```json
{json.dumps(report["representativeResults"], indent=2)}
```

See `queries.sql` for book list, Luke 1:1 passage, Luke 1 notes and overlap queries.
See `README.md` for import instructions, schema mapping and fidelity boundaries.
No upstream USX XSD validation, live DB write, commit, push, publish or RLS deployment.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        convert(args.source.resolve(), args.out)
    except Exception as error:
        output = args.out.resolve()
        if ROOT / "dist" in output.parents:
            output.mkdir(parents=True, exist_ok=True)
            (output / "rejection.json").write_text(
                json.dumps({"status": "rejected", "reason": str(error)}, indent=2) + "\n"
            )
        raise


if __name__ == "__main__":
    main()
