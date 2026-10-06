"""Validate a local Corpora content package, not an upstream DBL bundle."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lxml import etree

from .validate_xml import DRAFT, Q, grammar, load, require, validate


def confined(folder, uri, code):
    parts = urlsplit(uri)
    require(
        not parts.scheme and not parts.netloc and not parts.query and not parts.fragment,
        code,
        "Resource paths must be local without URI components",
    )
    target = (folder / unquote(parts.path)).resolve()
    require(
        parts.path and not parts.path.startswith("/") and target.is_relative_to(folder.resolve()),
        code,
        "Resource paths must stay inside the package",
    )
    require(target.is_file(), code, f"Missing package resource: {uri}")
    return target


def normalize_content(element):
    """Remove formatting whitespace without joining words across inline markup."""
    structural = {"document", "collection", "metadata", "table", "row"}
    name = etree.QName(element).localname
    if name in structural:
        if element.text and not element.text.strip():
            element.text = None
        for child in list(element):
            normalize_content(child)
            if child.tail and not child.tail.strip():
                child.tail = None
            if (
                child.tag == "para"
                and not len(child)
                and not child.text
                and child.get("style") != "b"
                and not child.get(Q + "id")
            ):
                element.remove(child)
        return

    slots = []

    def collect(node):
        slots.append((node, "text"))
        for child in node:
            if child.tag == "note":
                normalize_content(child)
            else:
                collect(child)
            slots.append((child, "tail"))

    collect(element)
    previous = ""
    for node, field in slots:
        value = re.sub(r"\s+", " ", getattr(node, field) or "")
        if not previous or previous.endswith(" "):
            value = value.lstrip(" ")
        setattr(node, field, value or None)
        if value:
            previous = value
    for node, field in reversed(slots):
        value = getattr(node, field)
        if value:
            setattr(node, field, value.rstrip(" ") or None)
            break
    # An empty inline span cannot own a whitespace-only content array.
    # Move its word separator into the enclosing flow, keeping its identity.
    for node, field in reversed(slots):
        if field != "text" or node is element or len(node):
            continue
        if node.text and not node.text.strip():
            parent = node.getparent()
            sibling = node.getprevious()
            if sibling is None:
                parent.text = (parent.text or "") + node.text
            else:
                sibling.tail = (sibling.tail or "") + node.text
            node.text = None


def xml_json(element):
    name = etree.QName(element)
    content = []
    if element.text:
        content.append(element.text)
    for child in element:
        content.append(xml_json(child))
        if child.tail:
            content.append(child.tail)
    value = {
        "name": name.localname,
        "namespace": name.namespace or "",
        "attributes": dict(element.attrib),
    }
    if any(isinstance(item, dict) or item.strip() for item in content):
        value["content"] = content
    return value


def validate_package(folder):
    folder = Path(folder).resolve()
    shape = etree.RelaxNG(etree.parse(str(DRAFT / "schema/package.rng")))
    trees = {}
    for name in ["metadata.xml", "license.xml", "release/styles.xml"]:
        trees[name] = load(confined(folder, name, "PKG-001"))
        require(shape.validate(trees[name]), "PKG-002", str(shape.error_log.last_error))
    metadata = trees["metadata.xml"].getroot()
    require(
        metadata.get("version") == "0.1.0"
        and metadata.find("format/corporaVersion").text == "0.1.0",
        "PKG-003",
        "The package declares the supported content draft version",
    )
    license_ = trees["license.xml"].getroot()
    styles = trees["release/styles.xml"].getroot()
    require(
        license_.get("id") == metadata.get("id"), "PKG-003", "License identifies the same package"
    )
    rights = license_.find("publicationRights")
    require(
        rights.get("status") in {"unspecified", "granted", "denied"},
        "PKG-003",
        "Permission status is explicit",
    )
    require(
        rights.get("status") != "unspecified" or len(rights) == 0,
        "PKG-003",
        "Unspecified rights cannot imply individual permission flags",
    )
    resources = {}
    for resource in metadata.findall("manifest/resource"):
        uri = resource.get("uri")
        require(uri not in resources, "PKG-004", "Resource URIs must be unique")
        path = confined(folder, uri, "PKG-004")
        data = path.read_bytes()
        algorithm = resource.get("checksumAlgorithm", "md5")
        require(algorithm in {"md5", "sha256"}, "PKG-004", "Unknown checksum algorithm")
        require(
            int(resource.get("size")) == len(data)
            and hashlib.new(algorithm, data).hexdigest() == resource.get("checksum"),
            "PKG-004",
            f"Resource byte size/checksum differs: {uri}",
        )
        resources[uri] = path
    delivered = {
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and p.name != "metadata.xml"
    }
    require(
        set(resources) == delivered,
        "PKG-004",
        "Manifest must list all delivered resources except metadata.xml",
    )
    names = [n.get("id") for n in metadata.findall("names/name")]
    require(len(names) == len(set(names)), "PKG-005", "Name identities must be unique")
    structures = metadata.findall("source/structure") + metadata.findall(
        "publications/publication/structure"
    )
    documents = {}
    for structure in structures:
        selected_names = set()
        for entry in structure.iter("content"):
            require(
                entry.get("name") in names and entry.get("name") not in selected_names,
                "PKG-005",
                "Content selects a unique declared name within its structure",
            )
            selected_names.add(entry.get("name"))
            uri = entry.get("src")
            require(
                uri in resources and uri.endswith(".usx"),
                "PKG-005",
                "Content selects a manifested USX file",
            )
            documents[uri] = resources[uri]
        if structure.getparent().tag == "source":
            require(
                selected_names == set(names),
                "PKG-005",
                "Source content inventory must include all named content",
            )
    style_ids = [s.get("id") for s in styles.findall("style")]
    require(len(style_ids) == len(set(style_ids)), "PKG-006", "Style IDs must be unique")
    style_map = {s.get("id"): s for s in styles.findall("style")}
    physical_style_names = {
        "page",
        "position",
        "page-break-before",
        "page-break-after",
        "page-break-inside",
        "break-before",
        "break-after",
    }
    require(
        not any(p.get("name") in physical_style_names for p in styles.iter("property")),
        "PKG-006",
        "Styles cannot impose source page constraints",
    )
    content_schema = grammar()
    roots = {}
    anchors = {}
    for uri, path in documents.items():
        validate(path, content_schema)
        root = load(path).getroot()
        for entry in metadata.iter("content"):
            if entry.get("src") == uri:
                require(
                    entry.get("name") == root.get("id"),
                    "PKG-005",
                    "Content names select the document identity",
                )
        roots[path] = root
        json_uri = uri.replace("/USX_1/", "/JSON_1/").removesuffix(".usx") + ".json"
        if json_uri in resources:
            value = json.loads(resources[json_uri].read_text())
            normalized = copy.deepcopy(root)
            normalize_content(normalized)
            require(
                value == xml_json(root) == xml_json(normalized),
                "PKG-009",
                "JSON must encode canonical ordered XML content without empty content properties",
            )
        ids = [root.get("id")]
        for element in root.iter():
            content_id = element.get(Q + "id") or element.get("link-id")
            if content_id:
                ids.append(content_id)
            style_id = element.get(Q + "style-id")
            if style_id:
                require(style_id in style_map, "PKG-006", f"Missing style definition: {style_id}")
                style = style_map[style_id]
                require(
                    style.get("semantic") == element.get(Q + "semantic")
                    and style.get("nodeType") == element.get(Q + "node-type"),
                    "PKG-006",
                    "Style semantic/node type must match content",
                )
            for name, value in element.attrib.items():
                if name == "link-href" and urlsplit(value).scheme:
                    continue
                require(
                    not any(v in value.lower() for v in (".xhtml", ".html", "epub-spine")),
                    "PKG-007",
                    "Content attributes cannot expose source-container mappings",
                )
        require(
            len(ids) == len(set(ids)),
            "PKG-008",
            "Canonical anchor IDs are document-local and unique",
        )
        anchors[path] = set(ids)
    for path, root in roots.items():
        for element in root.iter():
            href = element.get("link-href")
            if not href:
                continue
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                continue  # External references are not fetched or certified.
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            require(
                target in roots and not parts.query,
                "PKG-008",
                f"Invalid local content link: {href}",
            )
            require(
                not parts.fragment or unquote(parts.fragment) in anchors[target],
                "PKG-008",
                f"Missing local anchor: {href}",
            )
    for uri, path in resources.items():
        require(
            "conversion" not in uri.lower() and path.suffix not in {".epub", ".sqlite"},
            "PKG-007",
            "Conversion artifacts are outside the publication package",
        )
    return {
        "content_files": len(documents),
        "style_definitions": len(style_map),
        "manifest_resources": len(resources),
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("folder", type=Path)
    args = cli.parse_args()
    print("PASS:", validate_package(args.folder))
