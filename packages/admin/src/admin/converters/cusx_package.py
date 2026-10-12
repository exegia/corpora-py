"""The multi-document C-USX 0.2 contract and its source-preserving EPUB writer."""

import json
import posixpath
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET

from corpora_linking import TextSnapshot

from ..parsers.cusx_sources import link_attributes, read_cusx_source
from ..parsers.epub_structure import (
    nav_entries,
    read_epub_structure,
    safe_path,
    target,
    walk,
)
from ..parsers.schema import Document, SourceFormat, Unit
from .cusx import CX, MAX_BYTES, PROFILE, STREAM, digest, document_xml, encoded
from .cusx_schema import PackageManifest


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: compact(item)
            for key, item in value.items()
            if not (key in ("children", "source_attrs") and item == [])
            and not (key in ("source_attrs", "namespaces") and item == {})
            and not (key == "namespace" and item is None)
        }
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def _relocate(
    unit: Unit,
    origin: str,
    output: str,
    ids: dict[tuple[str, str], str],
    first: dict[str, str],
    assets: dict[str, bytes],
    diagnostics: list[str],
) -> None:
    for node in walk(unit):
        # These embedded URL grammars require a dedicated CSS/srcset parser.
        # Retain source evidence and expose the portability gap explicitly.
        if (
            node.attrs.get("srcset")
            or re.search(r"url\s*\(|@import\b", node.attrs.get("style", ""), re.IGNORECASE)
            or (
                node.type == "style"
                and re.search(
                    r"url\s*\(|@import\b",
                    "".join(
                        token.text + token.after for child in walk(node) for token in child.tokens
                    ),
                    re.IGNORECASE,
                )
            )
        ):
            diagnostics.append(
                f"Embedded CSS/srcset URLs retained without relocation: {origin}; "
                "a reader must resolve these against the original source path"
            )
        for key in link_attributes(node):
            href = node.attrs.get(key)
            if not href:
                continue
            if key == "target" and len(href.split()) > 1:
                continue
            if node.type == "image" and node.attrs.get("evidence"):
                node.attrs[key] = posixpath.relpath(href, posixpath.dirname(output))
                continue
            resolved = target(origin, href)
            if resolved is None:
                continue
            path, fragment = resolved
            if path in first:
                dest = ids.get((path, fragment)) if fragment else first[path]
                if dest is None:
                    diagnostics.append(f"Unresolved source link: {origin} -> {href}")
                    continue
                new = posixpath.relpath(dest, posixpath.dirname(output))
                if urlsplit(href).query:
                    new += "?" + urlsplit(href).query
                if fragment:
                    new += "#" + quote(fragment, safe="")
            elif "assets/" + path in assets:
                new = posixpath.relpath("assets/" + path, posixpath.dirname(output))
                parsed = urlsplit(href)
                if parsed.query:
                    new += "?" + parsed.query
                if fragment:
                    new += "#" + quote(fragment, safe="")
            else:
                diagnostics.append(f"Unresolved source resource: {origin} -> {href}")
                continue
            node.source_attrs[key] = href
            node.attrs[key] = new


def write_package(
    source: Path,
    output: Path,
    *,
    source_format: SourceFormat,
    name: str,
    description: str,
    author_sub: str | None,
    category: str,
) -> Path:
    package_id = "urn:uuid:" + str(uuid.uuid4())
    identity = {
        "work_id": "urn:uuid:" + str(uuid.uuid4()),
        "edition_id": "urn:uuid:" + str(uuid.uuid4()),
        "package_id": package_id,
    }
    members: dict[str, bytes] = {}
    entries = []
    reading_order = []
    supplementary = []
    diagnostics = [
        "no references approved or published",
        "source trace ranges are not native EPUB CFIs or selection mappings",
    ]
    structure = (
        read_epub_structure(str(source))
        if source_format == SourceFormat.EPUB
        else read_cusx_source(source, source_format)
    )
    metadata = structure.metadata
    diagnostics.extend(structure.diagnostics)
    members.update(structure.assets)
    evidence = None
    if source_format != SourceFormat.EPUB:
        evidence = "assets/source/" + safe_path(source.name)
        if evidence in members:
            raise ValueError("Source evidence path collides with a supplied resource")
        members[evidence] = source.read_bytes()
    navigation = structure.navigation
    ids, first = {}, {}
    for i, section in enumerate(structure.sections, start=1):
        path = f"documents/{i:04d}.usx"
        first.setdefault(section.source_path, path)
        for unit in walk(section.unit):
            source_id = unit.attrs.get("id") or unit.attrs.get("xml:id")
            if source_id:
                ids[section.source_path, source_id] = path
    for i, section in enumerate(structure.sections, start=1):
        path = f"documents/{i:04d}.usx"
        _relocate(section.unit, section.source_path, path, ids, first, members, diagnostics)
        meta = metadata.model_copy(deep=True)
        if source_format == SourceFormat.EPUB:
            meta.extra["epub:html-attributes"] = encoded(section.html_attrs).decode()
            meta.extra["epub:namespaces"] = encoded(section.namespaces).decode()
        if section.head:
            _relocate(section.head, section.source_path, path, ids, first, members, diagnostics)
            meta.extra["epub:head"] = encoded(
                compact(section.head.model_dump(mode="json"))
            ).decode()
        document = Document(metadata=meta, units=[section.unit])
        entries.append(
            _write_document(
                members,
                identity,
                document,
                i,
                {
                    "label": section.label,
                    "role": section.role,
                    "source": {
                        "path": section.source_path,
                        "fragment": section.fragment,
                        "start_event": section.start,
                        "end_event": section.end,
                        **getattr(section, "source_details", {}),
                    },
                    "linear": section.linear,
                    "in_spine": section.in_spine,
                },
            )
        )
        (reading_order if section.in_spine else supplementary).append(path)
    for group in navigation.values():
        for item in nav_entries(group):
            source_path = item.get("source_path")
            if not source_path:
                continue
            fragment = item.get("fragment", "")
            doc_id = ids.get((source_path, fragment)) if fragment else first.get(source_path)
            if doc_id is None:
                raise ValueError(f"Unresolved navigation target: {source_path}#{fragment}")
            item["target"] = {"document_id": doc_id, "fragment": fragment}
    if not any(entry["characters"] for entry in entries):
        raise ValueError("source contains no extractable text")
    members["references.json"] = encoded([])
    members["mappings.json"] = encoded(
        {"mappings": [], "diagnostics": ["native selection mappings unavailable"]}
    )
    manifest = {
        "format": PROFILE,
        "name": name,
        "description": description,
        "category": category,
        "created_by": author_sub,
        "identity": identity,
        "source": {
            "filename": source.name,
            "format": source_format.value,
            "revision": digest(source.read_bytes()),
            **({"evidence": evidence} if evidence else {}),
        },
        "stream": {"id": STREAM, "offset_unit": "unicode-scalar", "normalization": "preserve"},
        "documents": entries,
        "reading_order": reading_order,
        "supplementary": supplementary,
        "navigation": navigation,
        "assets": sorted(path for path in members if path.startswith("assets/")),
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "files": {key: digest(data) for key, data in members.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", encoded(manifest))
            for key, data in members.items():
                archive.writestr(key, data)
        summary = validate_package(temporary)
        if not summary["valid"]:
            raise ValueError("; ".join(summary["reasons"]))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _write_document(members, identity, document: Document, i: int, info: dict) -> dict:
    path = f"documents/{i:04d}.usx"
    tree = f"trees/{i:04d}.json"
    snapshot = f"snapshots/{i:04d}.json"
    data = document_xml(document)
    text = "".join(ET.fromstring(data).itertext())
    endpoint = {**identity, "document_id": path, "revision": digest(data), "locators": []}
    members[path] = data
    members[tree] = encoded(compact(document.model_dump(mode="json")))
    members[snapshot] = encoded({"endpoint": endpoint, "stream_id": STREAM, "text": text})
    return {
        "id": path,
        "path": path,
        "tree": tree,
        "snapshot": snapshot,
        "identity": endpoint,
        "characters": len(text),
        **info,
    }


def _check_package(path: Path) -> tuple[dict, dict[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or sum(i.file_size for i in infos) > MAX_BYTES:
            raise ValueError("Duplicate or oversized C-USX members")
        for name in names:
            safe_path(name)
        members = {name: archive.read(name) for name in names}
    manifest = json.loads(members.pop("manifest.json"))
    PackageManifest.model_validate(manifest)
    if manifest["format"] != PROFILE or set(manifest["files"]) != set(members):
        raise ValueError("Unsupported profile or incomplete member inventory")
    if any(digest(data) != manifest["files"][name] for name, data in members.items()):
        raise ValueError("C-USX member checksum mismatch")
    identity = manifest["identity"]
    if set(identity) != {"work_id", "edition_id", "package_id"} or not all(identity.values()):
        raise ValueError("Invalid shared package identity")
    documents = manifest["documents"]
    if not documents:
        raise ValueError("C-USX requires at least one document")
    ids = [entry["id"] for entry in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate document identity")
    reading = manifest["reading_order"]
    supplementary = manifest["supplementary"]
    if (
        not reading
        or len(reading + supplementary) != len(set(reading + supplementary))
        or set(reading + supplementary) != set(ids)
    ):
        raise ValueError("Incomplete or duplicate reading order")
    if reading != [e["id"] for e in documents if e["in_spine"]] or supplementary != [
        e["id"] for e in documents if not e["in_spine"]
    ]:
        raise ValueError("Reading order differs from document inventory")
    expected = {"references.json", "mappings.json"}
    xml_ids = {}
    source_ids = {}
    source_first = {}
    relocated_links = []
    native_links = []
    for entry in documents:
        source_first.setdefault(entry["source"]["path"], entry["id"])
        paths = [entry["path"], entry["tree"], entry["snapshot"]]
        if (
            entry["id"] != entry["path"]
            or not entry["path"].startswith("documents/")
            or not (
                entry["tree"].startswith("trees/") and entry["snapshot"].startswith("snapshots/")
            )
            or any(p in expected for p in paths)
        ):
            raise ValueError("Invalid or reused document member path")
        expected.update(paths)
        data = members[entry["path"]]
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("XML entity declarations are unsupported")
        root = ET.fromstring(data)
        if root.tag != "usx" or root.get(f"{{{CX}}}profile") != PROFILE:
            raise ValueError("Invalid C-USX document profile")
        document = Document.model_validate_json(members[entry["tree"]])
        if document_xml(document) != data:
            raise ValueError("C-USX XML differs from parsed document projection")
        snapshot = TextSnapshot.model_validate_json(members[entry["snapshot"]])
        endpoint = snapshot.endpoint.model_dump(mode="json")
        if endpoint != entry["identity"] or endpoint != {
            **identity,
            "document_id": entry["id"],
            "revision": digest(data),
            "locators": [],
        }:
            raise ValueError("Document snapshot identity or revision mismatch")
        if snapshot.stream_id != STREAM or snapshot.text != "".join(root.itertext()):
            raise ValueError("snapshot text differs from the C-USX stream")
        if entry["characters"] != len(snapshot.text):
            raise ValueError("Incorrect document character count")
        anchors = [n.get("id") for n in root.iter() if n.get("id")]
        if len(anchors) != len(set(anchors)):
            raise ValueError("Duplicate document anchor")
        xml_ids[entry["id"]] = set(anchors)
        roots = list(document.units)
        if "epub:head" in document.metadata.extra:
            roots.append(Unit.model_validate_json(document.metadata.extra["epub:head"]))
        for unit in roots:
            for node in walk(unit):
                if unit in document.units:
                    source_id = node.attrs.get("id") or node.attrs.get("xml:id")
                    if source_id:
                        key = (entry["source"]["path"], source_id)
                        if key in source_ids:
                            raise ValueError("Duplicate source anchor across package documents")
                        source_ids[key] = entry["id"]
                for key in link_attributes(node):
                    if node.type == "image" and node.attrs.get("evidence"):
                        native_links.append((entry["path"], node.attrs[key]))
                    if key in node.source_attrs:
                        relocated_links.append(
                            (
                                entry["path"],
                                entry["source"]["path"],
                                node.source_attrs[key],
                                node.attrs[key],
                            )
                        )
    assets = manifest["assets"]
    if len(assets) != len(set(assets)) or any(not p.startswith("assets/") for p in assets):
        raise ValueError("Invalid asset inventory")
    expected.update(assets)
    evidence = manifest["source"].get("evidence")
    if evidence is not None and (
        evidence not in assets or digest(members[evidence]) != manifest["source"]["revision"]
    ):
        raise ValueError("Original source evidence is missing or differs from its revision")
    if expected != set(members):
        raise ValueError("Unexpected or missing C-USX members")
    for origin, href in native_links:
        resolved = target(origin, href)
        if resolved is None or resolved[0] not in assets:
            raise ValueError("Extracted PDF image points to a missing package asset")

    def source_destination(path, fragment):
        if path in source_first:
            return source_ids.get((path, fragment)) if fragment else source_first[path]
        return "assets/" + path if "assets/" + path in members else None

    for origin, source_path, source_href, href in relocated_links:
        resolved = target(origin, href)
        if resolved is None:
            raise ValueError("Relocated link must address a package member")
        dest, fragment = resolved
        if dest not in members or (dest in xml_ids and fragment and fragment not in xml_ids[dest]):
            raise ValueError("Relocated link points to a missing package member/anchor")
        source_target = target(source_path, source_href)
        if (
            source_target is None
            or dest != source_destination(*source_target)
            or fragment != source_target[1]
            or urlsplit(href).query != urlsplit(source_href).query
        ):
            raise ValueError("Relocated link differs from its source target")
    for group in manifest["navigation"].values():
        for entry in nav_entries(group):
            if "target" not in entry:
                if entry.get("source_path"):
                    raise ValueError("Unresolved package navigation")
                continue
            dest = entry["target"]
            if dest["document_id"] != source_destination(
                entry.get("source_path", ""), entry.get("fragment", "")
            ) or dest["fragment"] != entry.get("fragment", ""):
                raise ValueError("Navigation target differs from source path/fragment")
            if dest["document_id"] not in xml_ids or (
                dest["fragment"] and dest["fragment"] not in xml_ids[dest["document_id"]]
            ):
                raise ValueError("Invalid navigation document/anchor")
    if manifest["stream"] != {
        "id": STREAM,
        "offset_unit": "unicode-scalar",
        "normalization": "preserve",
    }:
        raise ValueError("Unsupported stream convention")
    if json.loads(members["references.json"]) != []:
        raise ValueError("Conversion cannot claim approved reference publication")
    mappings = json.loads(members["mappings.json"])
    if not isinstance(mappings, dict) or mappings.get("mappings") != []:
        raise ValueError("Conversion cannot claim native mapping evidence")
    from .cusx_pdf_review import check_pdf_review

    check_pdf_review(manifest, members)
    return manifest, members


def validate_package(path: Path) -> dict[str, Any]:
    try:
        manifest, members = _check_package(path)
        stats = {
            "documents": len(manifest["documents"]),
            "assets": len(manifest["assets"]),
            "characters": sum(e["characters"] for e in manifest["documents"]),
            "units": sum(
                sum(1 for u in ET.fromstring(members[e["path"]]).iter() if u.tag == f"{{{CX}}}unit")
                for e in manifest["documents"]
            ),
        }
        reasons = []
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        ET.ParseError,
    ) as exc:
        stats, reasons = {}, [str(exc)]
    summary = {
        "corpus": path.stem,
        "valid": not reasons,
        "stats": stats,
        "reasons": reasons,
        "checks": {"cusx_package_integrity": not reasons},
    }
    if not reasons:
        from .cusx_pdf_review import REPORT

        if REPORT in members:
            summary["source_reliability"] = json.loads(members[REPORT])
            summary["checks"]["pdf_review_evidence"] = True
    return summary


def read_package_documents(path: Path) -> list[tuple[TextSnapshot, bytes]]:
    """Validate the entire package before exposing revision-pinned XML assets."""
    manifest, members = _check_package(path)
    return [
        (TextSnapshot.model_validate_json(members[e["snapshot"]]), members[e["path"]])
        for e in manifest["documents"]
    ]
