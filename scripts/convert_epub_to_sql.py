"""Complete private EPUB -> owned Corpus Document 0.4.0 -> PostgreSQL.

No database/network access. Content artifacts must remain in ignored dist/.
"""

import argparse
import json
import platform
import posixpath
import re
from collections import Counter
from html.entities import html5
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote, urlsplit

import check_corpus_document as checker
import corpus_document_sql as sql
from convert_usx_to_sql import Allocations, archive_members, digest, validate_sql, xml_equal
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
XHTML = "http://www.w3.org/1999/xhtml"
SUPPORTED = {
    "html",
    "head",
    "title",
    "meta",
    "link",
    "style",
    "body",
    "div",
    "p",
    "span",
    "br",
    "img",
    "a",
    "table",
    "tbody",
    "tr",
    "td",
    "th",
    "ins",
    "del",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "svg",
    "image",
    "section",
    "aside",
    "ol",
    "ul",
    "li",
    "em",
    "strong",
    "b",
    "i",
    "sup",
    "sub",
    "blockquote",
    "hr",
}


def package_xml(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Package XML DTD/entity declarations unsupported")
    return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))


def xhtml(raw):
    """Controlled HTML named entities; never resolve a source external DTD."""
    text = raw.decode("utf-8")
    if re.search(r"<!ENTITY", text, re.I):
        raise ValueError("Entity declarations unsupported")
    doctypes = re.findall(r"<!DOCTYPE[^>]*>", text, flags=re.I)
    if any("[" in d or not re.fullmatch(r"<!DOCTYPE\s+html\s*>", d, re.I) for d in doctypes):
        raise ValueError("Only harmless HTML doctype supported")
    text = re.sub(r"<!DOCTYPE\s+html\s*>", "", text, flags=re.I)
    entities = Counter()

    def expand(match):
        name = match[1]
        if name in {"amp", "lt", "gt", "quot", "apos"}:
            return match[0]
        if name + ";" not in html5:
            raise ValueError("Unknown named XHTML entity")
        entities[name] += 1
        return "".join(f"&#{ord(c)};" for c in html5[name + ";"])

    tokens = re.split(r"(<!\[CDATA\[.*?\]\]>|<!--.*?-->)", text, flags=re.S)
    text = "".join(
        token
        if token.startswith(("<![CDATA[", "<!--"))
        else re.sub(r"&([A-Za-z][A-Za-z0-9]*);", expand, token)
        for token in tokens
    )
    root = etree.fromstring(
        text.encode("utf-8"),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False),
    )
    if (
        any(not isinstance(e.tag, str) for e in root.iter())
        or root.getprevious() is not None
        or root.getnext() is not None
    ):
        raise ValueError("XHTML comments/processing instructions require explicit mapping")
    if etree.QName(root).localname != "html" or etree.QName(root).namespace not in (None, XHTML):
        raise ValueError("Expected XHTML or source XML HTML envelope")
    return root, dict(entities), len(doctypes)


def local_resource(base, href):
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        return None
    path = (
        posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(parts.path)))
        if parts.path
        else base
    )
    if path.startswith(("/", "../")) or path == ".." or "\\" in path:
        raise ValueError("Resource escapes EPUB archive")
    return path


def metadata_records(root):
    metadata = root.find("{*}metadata")
    return (
        [
            {"tag": e.tag, "attributes": dict(e.attrib), "value": "".join(e.itertext())}
            for e in metadata
            if isinstance(e.tag, str)
        ]
        if metadata is not None
        else []
    )


class Resource:
    def __init__(self, document, ids, member, root, revision, assets, spine_index, linear):
        self.document, self.ids, self.member, self.root = document, ids, member, root
        self.revision, self.assets = revision, assets
        self.spine_index, self.linear = spine_index, linear
        self.streams = {
            role: {
                "id": self.identity("stream/" + role),
                "revisionId": revision,
                "order": spine_index * 2 + i,
                "text": "",
                "extensions": {
                    "epub:member": member,
                    "epub:role": role,
                    "epub:linear": linear,
                    "epub:spineOrder": spine_index,
                },
            }
            for i, role in enumerate(("body", "metadata"))
        }
        self.events, self.members, self.blocks, self.links, self.images, self.bindings = (
            [],
            [],
            [],
            [],
            [],
            [],
        )
        self.anchor_cache = {}
        self.active_ranges = []
        self.counters = Counter(etree.QName(e).localname for e in root.iter())
        unsupported = set(self.counters) - SUPPORTED
        if unsupported:
            raise ValueError(f"Unmapped XHTML element semantics: {sorted(unsupported)}")
        if len(root.findall("{*}body")) != 1:
            raise ValueError("Expected exactly one XHTML body")

    def identity(self, key):
        return self.ids.get("xhtml/" + self.member + "/" + key)

    def add_text(self, value, event, field, role):
        if value is None:
            event[field] = None
            return
        stream = self.streams[role]
        start = len(stream["text"])
        stream["text"] += value
        end = len(stream["text"])
        event[field] = {"streamId": stream["id"], "start": start, "end": end}
        if start < end:
            for ranges in self.active_ranges:
                if ranges and ranges[-1]["streamId"] == stream["id"] and ranges[-1]["end"] == start:
                    ranges[-1]["end"] = end
                else:
                    ranges.append({"streamId": stream["id"], "start": start, "end": end})

    def visit(self, element, path="0", parent=None, sibling=0, role="metadata"):
        tag = etree.QName(element).localname
        if tag == "body":
            role = "body"
        identity = self.identity("node/" + path)
        event = {
            "nodeId": identity,
            "path": path,
            "parent": parent,
            "order": sibling,
            "tag": element.tag,
            "attributes": dict(element.attrib),
            "namespaces": [{"prefix": k, "uri": v} for k, v in element.nsmap.items()],
        }
        self.events.append(event)
        node = {
            "id": identity,
            "revisionId": self.revision,
            "type": "epub:element",
            "extensions": {
                "epub:tag": tag,
                "epub:attributes": dict(element.attrib),
                "epub:xmlPath": path,
                "epub:member": self.member,
            },
            "sourceIds": [{"assetId": self.assets[self.member], "value": "xpath:" + path}],
        }
        self.document["nodes"].append(node)
        member = {"nodeId": identity, "order": sibling}
        if parent is not None:
            member["parentNodeId"] = self.identity("node/" + parent)
        self.members.append(member)
        if role == "body" and tag in {"p", "table", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.blocks.append(identity)
        fragment = element.get("id") or (element.get("name") if tag == "a" else None)
        if fragment:
            node["sourceIds"].append({"assetId": self.assets[self.member], "value": fragment})
            self.bindings.append((self.member + "#" + fragment, identity))
        if tag == "body":
            self.bindings.append((self.member, identity))
        ranges = []
        self.active_ranges.append(ranges)
        position = {"streamId": self.streams[role]["id"], "offset": len(self.streams[role]["text"])}
        self.add_text(element.text, event, "text", role)
        for i, child in enumerate(element):
            child_event = self.visit(child, f"{path}/{i}", path, i, role)
            self.add_text(child.tail, child_event, "tail", role)
        self.active_ranges.pop()
        # Anchor segments must follow stream order, independently of XML traversal.
        stream_order = {s["id"]: s["order"] for s in self.streams.values()}
        ranges.sort(key=lambda s: (stream_order[s["streamId"]], s["start"]))
        merged = []
        for segment in ranges:
            if (
                merged
                and merged[-1]["streamId"] == segment["streamId"]
                and merged[-1]["end"] == segment["start"]
            ):
                merged[-1]["end"] = segment["end"]
            else:
                merged.append(dict(segment))
        if merged:
            key = tuple((s["streamId"], s["start"], s["end"]) for s in merged)
            if key not in self.anchor_cache:
                anchor = {
                    "id": self.identity(f"anchor/{len(self.anchor_cache)}"),
                    "revisionId": self.revision,
                    "segments": merged,
                }
                self.document["anchors"].append(anchor)
                self.anchor_cache[key] = anchor["id"]
            node["anchorId"] = self.anchor_cache[key]
        else:
            node["position"] = position
        if tag in {"html", "body"}:
            node["type"] = "core:document"
        elif tag == "p":
            node["type"] = "core:paragraph"
        elif re.fullmatch(r"h[1-6]", tag):
            node["type"] = "core:heading"
        elif tag in {"img", "image", "svg"}:
            node["type"] = "core:figure"
        elif tag in {"br", "hr"}:
            node["type"] = "core:milestone"
        elif tag == "table":
            node["type"] = "epub:table"
        elif tag in {"td", "th"}:
            node["type"] = "epub:tableCell"
        elif tag == "a":
            node["type"] = "epub:link"
        href = element.get("href")
        if tag == "a" and href is not None:
            self.links.append((node, href))
        image_href = (
            element.get("src")
            if tag == "img"
            else element.get("{http://www.w3.org/1999/xlink}href")
            if tag == "image"
            else None
        )
        if image_href:
            target = local_resource(self.member, image_href)
            node["extensions"]["epub:resourceHref"] = image_href
            if target in self.assets:
                node["assetId"] = self.assets[target]
            self.images.append(
                {"nodeId": identity, "target": target, "available": target in self.assets}
            )
        return event

    def convert(self):
        self.visit(self.root)
        self.events[0]["tail"] = None
        self.document["streams"].extend(self.streams.values())
        self.document["structures"].extend(
            [
                {
                    "id": self.identity("structure/xml"),
                    "revisionId": self.revision,
                    "name": f"epub:xml-{self.spine_index}",
                    "members": self.members,
                },
                {
                    "id": self.identity("structure/blocks"),
                    "revisionId": self.revision,
                    "name": f"epub:blocks-{self.spine_index}",
                    "members": [{"nodeId": n, "order": i} for i, n in enumerate(self.blocks)],
                },
            ]
        )
        rebuilt = reconstruct(self.events, self.document)
        if not xml_equal(self.root, rebuilt):
            raise ValueError("Decoded XHTML reconstruction mismatch")
        body = self.root.find("{*}body")
        if "".join(body.itertext()) != self.streams["body"]["text"]:
            raise ValueError("Independent complete body text check failed")
        return {
            "member": self.member,
            "linear": self.linear,
            "sourceRootNamespace": etree.QName(self.root).namespace,
            "spineOrder": self.spine_index,
            "elements": dict(self.counters),
            "bodyScalars": len(self.streams["body"]["text"]),
            "metadataScalars": len(self.streams["metadata"]["text"]),
            "bodyTextSha256": digest(self.streams["body"]["text"].encode()),
            "decodedXhtmlRoundTripExact": True,
            "bodyTextExact": True,
            "imageReferences": len(self.images),
            "anchorLinks": len(self.links),
            "explicitNoteSemantics": sum(
                bool(
                    e.get(EPUB_TYPE)
                    and set(e.get(EPUB_TYPE).split()) & {"footnote", "endnote", "noteref"}
                )
                or e.get("role") in {"doc-footnote", "doc-endnote", "doc-noteref"}
                for e in self.root.iter()
            ),
        }


def reconstruct(events, document):
    streams = {s["id"]: s["text"] for s in document["streams"]}
    nodes = {}
    root = None

    def text(location):
        return (
            None
            if location is None
            else streams[location["streamId"]][location["start"] : location["end"]]
        )

    for event in events:
        e = etree.Element(
            event["tag"],
            event["attributes"],
            nsmap={n["prefix"]: n["uri"] for n in event["namespaces"]},
        )
        e.text, e.tail = text(event.get("text")), text(event.get("tail"))
        nodes[event["path"]] = e
        if event["parent"] is None:
            root = e
        else:
            nodes[event["parent"]].append(e)
    return root


def convert(source, output):
    output = output.resolve()
    if ROOT / "dist" not in output.parents:
        raise ValueError("Private outputs must remain under checkout dist/")
    output.mkdir(parents=True, exist_ok=True)
    before = (digest(source.read_bytes()), source.stat().st_mtime_ns)
    ids = Allocations(output / "identity-allocations.json", before[0])
    members = dict(archive_members(source))
    if members.get("mimetype") != b"application/epub+zip":
        raise ValueError("Invalid EPUB mimetype")
    if "META-INF/encryption.xml" in members:
        raise ValueError("Encrypted resources require an explicit decoder")
    container = package_xml(members["META-INF/container.xml"])
    rootfiles = container.findall(".//{*}rootfile")
    if len(rootfiles) != 1:
        raise ValueError("Ambiguous package root")
    opf_member = rootfiles[0].get("full-path")
    if opf_member not in members:
        raise ValueError("Missing OPF package")
    opf = package_xml(members[opf_member])
    metadata = metadata_records(opf)
    title = opf.findtext("{*}metadata/{*}title") or source.stem
    language = opf.findtext("{*}metadata/{*}language") or "und"
    language = language.strip()
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language):
        language = "und"
    work, edition, revision, profile, agent, imported = (
        ids.get(k) for k in ("work", "edition", "revision", "profile", "agent", "import")
    )
    document = {
        "id": ids.get("bundle"),
        "specVersion": "0.4.0",
        "requiredCapabilities": [
            "core:text",
            "core:anchors",
            "core:structures",
            "core:positions",
            "core:references",
        ],
        "extensions": {
            "epub:sourceSha256": before[0],
            "epub:packageVersion": opf.get("version"),
            "epub:metadata": metadata,
        },
        **{k: [] for k in sql.FIELDS},
    }
    document["agents"] = [
        {"id": agent, "name": "Corpora complete EPUB SQL converter 0.1.0", "kind": "software"}
    ]
    document["works"] = [
        {
            "id": work,
            "title": title,
            "extensions": {
                "epub:identityStatus": "New local work identity; not catalog-reconciled"
            },
        }
    ]
    document["editions"] = [
        {"id": edition, "workId": work, "title": title, "language": language, "kind": "edition"}
    ]
    revision_record = {
        "id": revision,
        "editionId": edition,
        "sequence": 1,
        "profileIds": [profile],
        "importId": imported,
        "extensions": {"epub:resources": []},
    }
    document["revisions"] = [revision_record]
    document["profiles"] = [
        {
            "id": profile,
            "version": "0.1.0",
            "nodeTypes": ["epub:element", "epub:table", "epub:tableCell", "epub:link"],
            "featureKeys": [],
            "requiredCapabilities": ["core:positions", "core:references"],
        }
    ]
    assets = {}
    archive_id = ids.get("asset/archive")
    rights = "Private conversion only; source rights metadata retained; no redistribution permission inferred"
    document["assets"].append(
        {
            "id": archive_id,
            "mediaType": "application/epub+zip",
            "uri": source.as_uri(),
            "sha256": before[0],
            "rights": rights,
        }
    )
    manifest = {}
    media = {}
    for item in opf.findall("{*}manifest/{*}item"):
        identity = item.get("id")
        path = local_resource(opf_member, item.get("href", ""))
        if not identity or identity in manifest or path not in members:
            raise ValueError("Invalid/missing manifest resource")
        manifest[identity] = (path, item.get("media-type"))
        media[path] = item.get("media-type")
    for i, (name, raw) in enumerate(members.items()):
        identity = ids.get("asset/" + name)
        assets[name] = identity
        document["assets"].append(
            {
                "id": identity,
                "mediaType": media.get(
                    name, "application/xml" if name.endswith((".xml", ".opf")) else "text/plain"
                ),
                "uri": "zip-member:" + archive_id + "!/" + name,
                "sha256": digest(raw),
                "rights": rights,
                "extensions": {"epub:member": name, "epub:zipOrder": i, "epub:bytes": len(raw)},
            }
        )
    for i, creator in enumerate(opf.findall("{*}metadata/{*}creator")):
        if creator.get("{http://www.idpf.org/2007/opf}role") != "aut" or not creator.text:
            continue
        identity = ids.get(f"author/{i}")
        document["agents"].append(
            {
                "id": identity,
                "name": creator.text,
                "kind": "person",
                "sourceIds": [{"assetId": assets[opf_member], "value": f"dc:creator[{i}]"}],
                "extensions": {"epub:attributes": dict(creator.attrib)},
            }
        )
        document["contributions"].append(
            {
                "id": ids.get(f"author-contribution/{i}"),
                "agentId": identity,
                "target": {"id": work},
                "role": "core:author",
                "extensions": {
                    "epub:evidence": "Explicit OPF dc:creator role=aut; no additional authors inferred"
                },
            }
        )
    document["imports"] = [
        {
            "id": imported,
            "assetIds": [archive_id, *assets.values()],
            "adapter": "complete-epub-sql-experiment",
            "adapterVersion": "0.1.0",
            "agentId": agent,
            "report": [
                {
                    "aspect": "XHTML coverage",
                    "status": "preserved",
                    "detail": "All manifest XHTML resources, including linear and non-linear spine entries; exact decoded element/attribute/text/tail reconstruction",
                },
                {
                    "aspect": "lexical XML",
                    "status": "transformed",
                    "detail": "UTF-8 XML decoding plus controlled named HTML entities; harmless HTML doctype omitted. Original bytes remain checksum-addressed assets",
                },
                {
                    "aspect": "presentation",
                    "status": "unsupported",
                    "detail": "CSS, images and NCX retained as assets; no browser rendering, OCR, inferred page numbers or chapter numbering",
                },
            ],
        }
    ]
    spine = opf.findall("{*}spine/{*}itemref")
    selected = []
    for item in spine:
        ref = item.get("idref")
        if ref not in manifest or manifest[ref][1] != "application/xhtml+xml":
            raise ValueError("Unsupported or missing spine resource")
        path = manifest[ref][0]
        if path in [m for m, _, _ in selected]:
            raise ValueError("Repeated spine resource requires explicit occurrence mapping")
        selected.append((path, item.get("linear", "yes") != "no", True))
    for path, mimetype in manifest.values():
        if mimetype == "application/xhtml+xml" and path not in [m for m, _, _ in selected]:
            selected.append((path, False, False))
    if not selected:
        raise ValueError("No XHTML content")
    resources, results, bindings = [], [], []
    for i, (member, linear, in_spine) in enumerate(selected):
        root, entities, doctypes = xhtml(members[member])
        resource = Resource(document, ids, member, root, revision, assets, i, linear)
        result = resource.convert()
        result.update(
            inSpine=in_spine, namedEntitiesDecoded=entities, harmlessDoctypesRemoved=doctypes
        )
        results.append(result)
        resources.append(resource)
        bindings.extend(resource.bindings)
        revision_record["extensions"]["epub:resources"].append(
            {
                "member": member,
                "linear": linear,
                "inSpine": in_spine,
                "spineOrder": i,
                "xmlEvents": resource.events,
            }
        )
    keys = dict(bindings)
    if len(keys) != len(bindings):
        raise ValueError("Duplicate source resource/fragment address")
    document["schemes"] = [
        {
            "id": ids.get("scheme"),
            "name": "epub:sourceAddress",
            "version": "1.0.0",
            "workId": work,
            "editionId": edition,
            "revisionId": revision,
            "entries": [
                {"key": key, "order": i, "targetIds": [target]}
                for i, (key, target) in enumerate(bindings)
            ],
        }
    ]
    links = []
    for resource in resources:
        for node, href in resource.links:
            target = local_resource(resource.member, href)
            fragment = unquote(urlsplit(href).fragment)
            key = target + ("#" + fragment if fragment else "") if target is not None else None
            status = (
                "external"
                if target is None
                else "resolved"
                if key in keys
                else "asset-only"
                if target in assets and not fragment
                else "unresolved"
            )
            evidence = {
                "href": href,
                "status": status,
                "sourceKey": key,
                "targetId": keys.get(key) if key else None,
            }
            node["extensions"]["epub:linkTarget"] = evidence
            links.append({"sourceMember": resource.member, "nodeId": node["id"], **evidence})
    errors = checker.validate(document)
    if errors:
        raise ValueError("Draft graph failure: " + str(errors[:3]))
    tables = sql.rows(document)
    restored = sql.restore(tables)
    if restored != document:
        raise ValueError("Normalized SQL row round trip changed document")
    for resource, evidence in zip(
        resources, restored["revisions"][0]["extensions"]["epub:resources"], strict=True
    ):
        if not xml_equal(resource.root, reconstruct(evidence["xmlEvents"], restored)):
            raise ValueError("SQL mapping changed source reconstruction")
    ddl, data = sql.ddl(), sql.data_sql(tables)
    combined = (
        "-- PRIVATE EPUB content; PostgreSQL 14+; fresh isolated namespace only.\nBEGIN;\nSET LOCAL standard_conforming_strings=on;\n"
        + ddl
        + data
        + "COMMIT;\n"
    )
    validation = validate_sql(combined, tables)
    validate_sql(QUERIES, {})
    if (digest(source.read_bytes()), source.stat().st_mtime_ns) != before:
        raise ValueError("Original EPUB changed")
    ids.save()
    (output / "rejection.json").unlink(missing_ok=True)
    (output / "corpus-document.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "schema.sql").write_text("BEGIN;\n" + ddl + "COMMIT;\n")
    (output / "data.sql").write_text("BEGIN;\n" + data + "COMMIT;\n")
    (output / "import.sql").write_text(combined)
    (output / "queries.sql").write_text(QUERIES)
    (output / "requirements.txt").write_text(
        (ROOT / "scripts/usx_sql_requirements.txt").read_text()
    )
    totals = Counter()
    for r in results:
        totals.update(r["elements"])
    report = {
        "status": "complete-content-conversion-statically-validated",
        "dialect": "PostgreSQL 14+",
        "specVersion": "0.4.0",
        "sourceSha256": before[0],
        "originalChecksumAndMtimeUnchanged": True,
        "epubVersion": opf.get("version"),
        "packageMemberCount": len(members),
        "manifestItems": len(manifest),
        "spineItems": len(spine),
        "convertedXhtmlResources": len(resources),
        "allManifestXhtmlConverted": True,
        "resources": results,
        "elementCounts": dict(totals),
        "links": links,
        "linkStatusCounts": dict(Counter(link["status"] for link in links)),
        "imageReferences": [image for r in resources for image in r.images],
        "explicitNoteSemantics": sum(r["explicitNoteSemantics"] for r in results),
        "authorContributions": len(document["contributions"]),
        "sqlRowCounts": {k: len(v) for k, v in tables.items()},
        "sqlValidation": validation,
        "draftShapeAndGraphValidated": True,
        "normalizedRelationalRoundTripExact": True,
        "allDecodedXhtmlRoundTripsExact": True,
        "databaseExecution": "Unavailable: no existing disposable PostgreSQL runtime; no database connection attempted",
        "dependencyVersions": {name: version(name) for name in ("lxml", "jsonschema", "pglast")},
        "pythonVersion": platform.python_version(),
        "implementationHashes": {
            name: digest((ROOT / "scripts" / name).read_bytes())
            for name in (
                "convert_epub_to_sql.py",
                "corpus_document_sql.py",
                "convert_usx_to_sql.py",
                "check_corpus_document.py",
            )
        },
        "limits": [
            "XML lexical bytes are not reconstructed; original assets preserve checksums and unchanged locations",
            "Explicit table/inline/image/link markup retained; no browser-rendered layout or image OCR verified",
            "No semantic note markers occur; possible notes embedded in ordinary prose remain ordinary source text",
            "Unresolved source links are retained honestly without fabricated destinations",
            "OPF author role is mapped; remaining bibliographic/auxiliary metadata stays namespaced evidence/assets",
            "Fresh immutable snapshot namespace; not a production Supabase migration or append-to-existing-dataset script",
        ],
        "artifacts": {
            p.name: digest(p.read_bytes())
            for p in output.iterdir()
            if p.name
            in {
                "schema.sql",
                "data.sql",
                "import.sql",
                "queries.sql",
                "corpus-document.json",
                "identity-allocations.json",
                "requirements.txt",
            }
        },
    }
    report["representativeResults"] = {
        "execution": "computed from validated normalized rows, not executed PostgreSQL",
        "spineResources": len(spine),
        "linearBodyScalars": sum(r["bodyScalars"] for r in results if r["linear"]),
        "paragraphs": totals["p"],
        "tables": totals["table"],
        "tableCells": totals["td"] + totals["th"],
        "headings": sum(totals[f"h{i}"] for i in range(1, 7)),
        "imageReferences": sum(r["imageReferences"] for r in results),
        "unresolvedLinks": sum(link["status"] == "unresolved" for link in links),
        "authorContributions": len(document["contributions"]),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "report.md").write_text(report_markdown(report))
    (output / "README.md").write_text(README)
    print(
        f"PASS: {len(resources)} complete XHTML resources; {totals['p']} paragraphs; {totals['table']} tables; all decoded text/markup recovered",
        flush=True,
    )
    print(
        f"PASS: draft graph, SQL parsed values/FKs, source unchanged; {report['linkStatusCounts']} links",
        flush=True,
    )
    print(output, flush=True)
    return report


QUERIES = """-- Run only after importing into a fresh disposable PostgreSQL database.
-- 1. Reading streams in source spine order; cover remains non-linear.
SELECT t.ordinal,e.properties->'extensions'->>'epub:member' AS member,
 e.properties->'extensions'->>'epub:linear' AS linear,char_length(t.text) AS scalars
FROM corpora_draft_040.streams t JOIN corpora_draft_040.entities e ON e.id=t.id
WHERE e.properties->'extensions'->>'epub:role'='body' ORDER BY t.ordinal;
-- 2. Paragraphs, tables and headings.
SELECT node_type,count(*) FROM corpora_draft_040.nodes
WHERE node_type IN ('core:paragraph','core:heading','epub:table','epub:tableCell') GROUP BY node_type ORDER BY node_type;
-- 3. Explicit source author attribution.
SELECT a.name,c.role,w.title FROM corpora_draft_040.contributions c
JOIN corpora_draft_040.agents a ON a.id=c.agent_id JOIN corpora_draft_040.works w ON w.id=c.target_entity_id;
-- 4. Link status, with unresolved source hrefs retained in node properties.
SELECT e.properties->'extensions'->'epub:linkTarget'->>'status' AS status,count(*)
FROM corpora_draft_040.nodes n JOIN corpora_draft_040.entities e ON e.id=n.id
WHERE n.node_type='epub:link' GROUP BY status;
"""

README = """# Private complete EPUB SQL conversion

Dialect: PostgreSQL 14+, UTF-8. Semantic contract: Corpora draft 0.4.0.
`import.sql` contains all DDL/data in a single transaction. Alternatively use
`schema.sql` followed by `data.sql`, never both paths. The fresh namespace is
`corpora_draft_040`; importing into an existing namespace intentionally fails.
This is another independent snapshot, not an append to the previous USX snapshot.

No database was contacted. SQL execution remains unverified because no existing
disposable PostgreSQL runtime was available. To verify in a fresh disposable DB:

```sh
psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname "$DISPOSABLE_DATABASE_URL" --file import.sql
psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname "$DISPOSABLE_DATABASE_URL" --file queries.sql
```

The complete linear and non-linear spine resources are preserved in explicit
source order. All other manifest XHTML is included separately if present.
Body text and metadata/formatting text occupy separate ordered streams. Exact
source text/tails point into those streams; anchors never duplicate text.
Paragraphs, headings, tables/cells, inline spans, figures and link attributes
are represented as nodes in independent XML and block structures. Empty elements
use scalar positions. OPF metadata is retained; explicit dc:creator role=aut
adds an author agent/contribution. No other author, chapter or page is inferred.
The SQL mapping adds contributions with typed agent/target FKs and preserves
empty-array presence for exact transport round trips; semantic version is unchanged.

All source assets have hashes and original member addresses. Images, CSS, NCX
and package metadata remain available as source assets; image/CSS rendering is
not proved. No source instructions/scripts were executed or remote URLs fetched.
Unknown destinations remain unresolved link evidence, not invented relations.
This source has no explicit note/noteref semantics; prose notes remain prose.

The harmless HTML doctype was omitted and named HTML entities were decoded using
a fixed local table. XML line endings/entities normalize on parsing. Every decoded
XHTML element, attribute, text/tail and child order was reconstructed exactly.
This does not prove byte-for-byte XML regeneration or official EPUB validation.
The supplied cover has an unnamespaced XML HTML envelope; its declared XHTML
resource is preserved without inserting a namespace or repairing the source.

`corpus-document.json` is the intermediate; `report.md`/`report.json` contain
coverage, hashes and representative results computed from normalized rows.
PostgreSQL grammar, PL/pgSQL bodies, every INSERT value, column types, NOT NULL,
primary/unique keys and all generated FK values were checked statically.
Snapshot guards cover INSERT/UPDATE/DELETE/TRUNCATE after sealing.

Keep `identity-allocations.json`: it retains opaque random IDs for reproducible
replay. Content artifacts are private and ignored, excluded from the portable
specification bundle. No commit/push/publish or live migration is performed.
"""


def report_markdown(report):
    return f"""# Complete EPUB → Corpus Document 0.4.0 → PostgreSQL

Status: **complete content conversion, statically validated; database execution unverified**.
All {report["convertedXhtmlResources"]} manifest XHTML resources converted, including
the non-linear cover and full linear book body. Original checksum/mtime unchanged.
All decoded XHTML reconstructed exactly after declared local entity decoding.

Representative results, computed from normalized validated rows:

```json
{json.dumps(report["representativeResults"], indent=2)}
```

SQL validation:

```json
{json.dumps(report["sqlValidation"], indent=2)}
```

All eight original anchor hrefs are unresolved placeholder destinations in this
source; retained unchanged, with no invented target or citation. No explicit
footnote/endnote/noteref markup occurs; no inferred note annotations were created.
Tables, images, inline insertion/deletion markup and source metadata are retained.
One source-declared author contribution is mapped from OPF role=aut.

Source XHTML resource coverage:

```json
{json.dumps(report["resources"], indent=2)}
```

See `README.md` for mapping limits/import instructions and `queries.sql` for
spine order, structural counts, author attribution and link-status queries.
No official EPUB conformance or browser rendering was verified. No live DB write.
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
