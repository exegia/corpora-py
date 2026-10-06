"""Offline conformance checker for the unpublished Corpora document contract."""

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1] / "specs/corpus-document/v0.4.0"
CAPABILITIES = {
    "core:text",
    "core:anchors",
    "core:structures",
    "core:references",
    "core:relations",
    "core:annotations",
    "core:positions",
}
CORE_TYPES = {
    f"core:{name}"
    for name in (
        "document",
        "section",
        "heading",
        "paragraph",
        "sentence",
        "clause",
        "word",
        "verse",
        "page",
        "figure",
        "milestone",
    )
}


def validate(document, capabilities=CAPABILITIES, external=None):
    """Return shape and graph errors; external maps bundle ids to loaded documents."""
    schema = json.loads((ROOT / "document.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    errors = [
        f"shape:{list(e.path)}: {e.message}"
        for e in Draft202012Validator(schema).iter_errors(document)
    ]
    if errors:
        return errors

    def json_values(value):
        if isinstance(value, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            errors.append("json:surrogate")
        elif isinstance(value, float) and not math.isfinite(value):
            errors.append("json:nonfinite")
        elif isinstance(value, dict):
            for key, child in value.items():
                json_values(key)
                json_values(child)
        elif isinstance(value, list):
            for child in value:
                json_values(child)

    json_values(document)
    external = external or {}
    tables = {
        k: document.get(k, [])
        for k in schema["properties"]
        if schema["properties"][k].get("type") == "array" and k != "requiredCapabilities"
    }
    records = [r for k, rows in tables.items() if k != "resolutions" for r in rows]
    by_id = {r["id"]: r for r in records}
    kinds = {r["id"]: k for k, rows in tables.items() if k != "resolutions" for r in rows}

    def require(condition, code):
        if not condition:
            errors.append(code)

    require(len(by_id) == len(records), "identity:duplicate")
    require(document["id"] not in by_id, "identity:bundle-collision")

    def link(identity, kind=None):
        require(
            identity in by_id and (kind is None or kinds.get(identity) == kind),
            f"link:{kind}:{identity}",
        )
        return by_id.get(identity, {})

    def endpoint(value):
        bundle = value.get("bundleId", document["id"])
        if bundle == document["id"]:
            require(value["id"] == document["id"] or value["id"] in by_id, "endpoint:missing-local")
        elif bundle in external:
            other = external[bundle]
            require(
                value["id"] == bundle
                or any(
                    isinstance(rows, list)
                    and any(isinstance(r, dict) and r.get("id") == value["id"] for r in rows)
                    for rows in other.values()
                ),
                "endpoint:missing-external",
            )
        # An unloaded external endpoint is a declared boundary, not verified existence.

    required = set(document["requiredCapabilities"])
    for profile in tables["profiles"]:
        required.update(profile["requiredCapabilities"])
    require(required <= capabilities, "capability:unsupported-required")
    for r in records:
        for source in r.get("sourceIds", []):
            link(source["assetId"], "assets")
        if "revisionId" in r:
            link(r["revisionId"], "revisions")
    for collection in tables["collections"]:
        orders = []
        for member in collection["members"]:
            link(member["workId"], "works")
            orders.append(member["order"])
            if "editionId" in member:
                edition = link(member["editionId"], "editions")
                require(edition.get("workId") == member["workId"], "collection:edition-work")
        require(len(set(orders)) == len(orders), "collection:duplicate-order")
    for edition in tables["editions"]:
        link(edition["workId"], "works")
    seen_revision = set()
    for revision in tables["revisions"]:
        link(revision["editionId"], "editions")
        pair = (revision["editionId"], revision["sequence"])
        require(pair not in seen_revision, "revision:duplicate-sequence")
        seen_revision.add(pair)
        if "previousRevisionId" in revision:
            previous = link(revision["previousRevisionId"], "revisions")
            require(
                previous.get("editionId") == revision["editionId"]
                and previous.get("sequence", 0) < revision["sequence"],
                "revision:invalid-predecessor",
            )
        for profile_id in revision["profileIds"]:
            link(profile_id, "profiles")
        if "importId" in revision:
            link(revision["importId"], "imports")
    stream_orders = set()
    for stream in tables["streams"]:
        pair = (stream["revisionId"], stream["order"])
        require(pair not in stream_orders, "stream:duplicate-order")
        stream_orders.add(pair)
        require(not any(0xD800 <= ord(c) <= 0xDFFF for c in stream["text"]), "text:surrogate")
    for anchor in tables["anchors"]:
        previous = None
        for segment in anchor["segments"]:
            stream = link(segment["streamId"], "streams")
            require(stream.get("revisionId") == anchor["revisionId"], "anchor:revision")
            require(
                0 <= segment["start"] < segment["end"] <= len(stream.get("text", "")),
                "anchor:bounds",
            )
            position = (stream.get("order", -1), segment["start"], segment["end"])
            if previous:
                require(
                    position[0] > previous[0]
                    or (position[0] == previous[0] and position[1] >= previous[2]),
                    "anchor:overlap-or-order",
                )
            previous = position
    for node in tables["nodes"]:
        revision = by_id.get(node["revisionId"], {})
        profiles = [by_id.get(i, {}) for i in revision.get("profileIds", [])]
        require(
            node["type"] in CORE_TYPES
            or (
                not node["type"].startswith("core:")
                and any(node["type"] in p.get("nodeTypes", []) for p in profiles)
            ),
            "profile:undeclared-type",
        )
        for feature in node.get("features", {}):
            require(
                feature.startswith("core:")
                or any(feature in p.get("featureKeys", []) for p in profiles),
                "profile:undeclared-feature",
            )
        if "anchorId" in node:
            anchor = link(node["anchorId"], "anchors")
            require(anchor.get("revisionId") == node["revisionId"], "node:anchor-revision")
        if "assetId" in node:
            link(node["assetId"], "assets")
        if "position" in node:
            require("core:positions" in required, "position:capability")
            position = node["position"]
            stream = link(position["streamId"], "streams")
            require(stream.get("revisionId") == node["revisionId"], "position:revision")
            require(position["offset"] <= len(stream.get("text", "")), "position:bounds")
    names = set()
    for structure in tables["structures"]:
        key = (structure["revisionId"], structure["name"])
        require(key not in names, "structure:duplicate-name")
        names.add(key)
        members = {m["nodeId"]: m for m in structure["members"]}
        require(len(members) == len(structure["members"]), "structure:duplicate-node")
        orders = set()
        for m in structure["members"]:
            node = link(m["nodeId"], "nodes")
            require(node.get("revisionId") == structure["revisionId"], "structure:revision")
            pair = (m.get("parentNodeId"), m["order"])
            require(pair not in orders, "structure:duplicate-sibling-order")
            orders.add(pair)
            path = {m["nodeId"]}
            parent = m.get("parentNodeId")
            while parent:
                require(parent in members, "structure:missing-parent")
                if parent in path:
                    errors.append("structure:cycle")
                    break
                path.add(parent)
                parent = members.get(parent, {}).get("parentNodeId")
    for contribution in tables["contributions"]:
        link(contribution["agentId"], "agents")
        endpoint(contribution["target"])
    for r in tables["annotations"] + tables["relations"]:
        link(r["agentId"], "agents")
        for value in r.get("sources", []) + r["targets"]:
            endpoint(value)
        for asset in r.get("evidenceAssetIds", []):
            link(asset, "assets")
        for block in r.get("body", []):
            for mark in block.get("marks", []):
                require(
                    0 <= mark["start"] < mark["end"] <= len(block["text"]), "annotation:mark-bounds"
                )
                if "target" in mark:
                    endpoint(mark["target"])
    for imported in tables["imports"]:
        link(imported["agentId"], "agents")
        for asset in imported["assetIds"]:
            link(asset, "assets")
    for scheme in tables["schemes"]:
        revision = link(scheme["revisionId"], "revisions")
        edition = link(scheme["editionId"], "editions")
        link(scheme["workId"], "works")
        require(
            revision.get("editionId") == scheme["editionId"]
            and edition.get("workId") == scheme["workId"],
            "scheme:scope",
        )
        keys, orders = set(), set()
        for entry in scheme["entries"]:
            require(
                entry["key"] not in keys and entry["order"] not in orders,
                "scheme:duplicate-key-or-order",
            )
            keys.add(entry["key"])
            orders.add(entry["order"])
            for target in entry["targetIds"]:
                node = link(target, "nodes")
                require(node.get("revisionId") == scheme["revisionId"], "scheme:target-revision")
    for resolution in tables["resolutions"]:
        reference = resolution["reference"]
        scheme = by_id.get(reference["schemeId"])
        available = (
            scheme
            and kinds.get(reference["schemeId"]) == "schemes"
            and all(reference[k] == scheme[k] for k in ("editionId", "revisionId"))
            and reference["schemeVersion"] == scheme["version"]
        )
        entries = {e["key"]: e for e in scheme["entries"]} if available else {}
        start, end = (
            entries.get(reference["startKey"]),
            entries.get(reference.get("endKey", reference["startKey"])),
        )
        status = resolution["status"]
        require(bool(available) == (status != "unavailable"), "resolution:availability")
        if status == "resolved":
            require(bool(start and end) and start["order"] <= end["order"], "resolution:range")
            if start and end:
                expected = list(
                    dict.fromkeys(
                        t
                        for e in sorted(entries.values(), key=lambda x: x["order"])
                        if start["order"] <= e["order"] <= end["order"]
                        for t in e["targetIds"]
                    )
                )
                require(resolution["targetIds"] == expected, "resolution:targets")
        else:
            require(not resolution["targetIds"], "resolution:nonresolved-targets")
            require(bool(resolution.get("reason")), "resolution:missing-reason")
        require(
            (len(resolution["candidates"]) >= 2) == (status == "ambiguous"), "resolution:candidates"
        )
        if status == "unresolved":
            require(not start or not end or start["order"] > end["order"], "resolution:resolvable")
        for target in resolution["targetIds"] + [
            t for candidate in resolution["candidates"] for t in candidate
        ]:
            node = link(target, "nodes")
            require(node.get("revisionId") == reference["revisionId"], "resolution:target-scope")
    return errors


def check_fixtures():
    module_spec = importlib.util.spec_from_file_location("corpora_xml", ROOT / "xml_codec.py")
    codec = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(codec)
    schemas = [json.loads(p.read_text()) for p in sorted(ROOT.glob("*.schema.json"))]
    assert len({s["$id"] for s in schemas}) == len(schemas), "duplicate schema IDs"
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    index = json.loads((ROOT / "fixtures/index.json").read_text())
    actual = {p.name for p in (ROOT / "fixtures").glob("*.json")} - {"index.json"}
    assert actual == set(index), "fixture index mismatch"
    for name, expected in index.items():
        document = json.loads((ROOT / "fixtures" / name).read_text())
        errors = validate(document)
        if expected:
            assert any(e.startswith(expected) for e in errors), (name, expected, errors)
        else:
            assert not errors, (name, errors)
        assert json.loads(json.dumps(document, ensure_ascii=False)) == document
        assert codec.decode(codec.encode(document)) == document
        if not expected:
            for profile in document.get("profiles", []):
                Draft202012Validator(
                    schemas_by_name(schemas, "profile.schema.json"), registry=registry
                ).validate(profile)
            for resolution in document.get("resolutions", []):
                Draft202012Validator(
                    schemas_by_name(schemas, "resolution.schema.json"), registry=registry
                ).validate(resolution)
    for invalid in (b"<!DOCTYPE x><x/>", b"<!ENTITY x 'y'><x/>"):
        try:
            codec.decode(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("XML declaration accepted")
    print(f"PASS: {len(index)} indexed fixtures; shape, graph, JSON/XML round trips")


def schemas_by_name(schemas, name):
    return next(s for s in schemas if s["$id"].endswith(":" + name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", type=Path)
    parser.add_argument(
        "--bundle", type=Path, help="Write deterministic content manifest into this directory"
    )
    args = parser.parse_args()
    if args.document:
        errors = validate(json.loads(args.document.read_text()))
        for error in errors:
            print(error)
        return int(bool(errors))
    check_fixtures()
    if args.bundle:
        if args.bundle.exists() and any(args.bundle.iterdir()):
            parser.error("Bundle destination must be empty; use a new directory")
        args.bundle.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            ROOT,
            args.bundle / "specs/corpus-document/v0.4.0",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copyfile(ROOT.parent / "README.md", args.bundle / "specs/corpus-document/README.md")
        (args.bundle / "scripts").mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__), args.bundle / "scripts/check_corpus_document.py")
        experiment = Path(__file__).with_name("run_corpus_document_experiments.py")
        if experiment.exists():
            shutil.copyfile(experiment, args.bundle / "scripts/run_corpus_document_experiments.py")
            baseline = Path(__file__).resolve().parents[1] / "packages/admin/src/admin/parsers"
            destination = args.bundle / "packages/admin/src/admin/parsers"
            if baseline.exists():
                destination.mkdir(parents=True, exist_ok=True)
                for name in ("schema.py", "_plain.py"):
                    shutil.copyfile(baseline / name, destination / name)
        files = {
            str(p.relative_to(args.bundle)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(args.bundle.rglob("*"))
            if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts
        }
        manifest = {"specVersion": "0.4.0", "status": "unpublished-draft", "files": files}
        (args.bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"PASS: pinned manifest for {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
