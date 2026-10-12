"""Versioned C-USX ZIP projection of the existing parsed document tree.

This profile preserves the parser output, not a full USX scripture or graph
projection. It never invents scripture identities or original-file anchors.
"""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from corpora_linking import TextSnapshot

from ..parsers import PARSERS
from ..parsers.schema import Document, SourceFormat, Unit

CX = "urn:corpora:usx-extension:0.1"
LEGACY_PROFILE = "corpora-cusx-package/0.1.0"
PROFILE = "corpora-cusx-package/0.2.0"
STREAM = "cusx-itertext/v1"
MAX_BYTES = 256 * 1024 * 1024
MEMBERS = {"document.usx", "document.json", "snapshot.json", "references.json", "mappings.json"}
ET.register_namespace("cx", CX)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _unit(parent: ET.Element, unit: Unit, depth: int = 0, *, legacy: bool = False) -> None:
    if depth > 200:
        raise ValueError("source structure exceeds the supported nesting depth")
    # Source IDs remain source metadata; they do not become global anchors.
    node = ET.SubElement(parent, f"{{{CX}}}unit", {"type": unit.type})
    node.set("attributes", encoded(unit.attrs).decode())
    if not legacy:
        if unit.namespace:
            node.set("namespace", unit.namespace)
        if unit.namespaces:
            node.set("namespaces", encoded(unit.namespaces).decode())
        if unit.source_attrs:
            node.set("source-attributes", encoded(unit.source_attrs).decode())
        source_id = unit.attrs.get("id") or unit.attrs.get("xml:id")
        if source_id:
            node.set("id", source_id)
    if unit.id is not None:
        node.set("source-id", unit.id)
    if unit.label is not None:
        node.set("label", unit.label)
    if unit.tokens:
        para = ET.SubElement(node, "para", {"style": "p"})
        para.text = "".join(token.text + token.after for token in unit.tokens)
    for child in unit.children:
        _unit(node, child, depth + 1, legacy=legacy)
    if legacy and unit.tokens and not unit.children:
        # Deliberate converted-stream separator, never a native-file offset.
        node.tail = "\n\n"


def document_xml(document: Document, *, profile: str = PROFILE) -> bytes:
    root = ET.Element("usx", {"version": "3.1", f"{{{CX}}}profile": profile})
    for unit in document.units:
        _unit(root, unit, legacy=profile == LEGACY_PROFILE)
    for node in root.iter():
        for text in (node.text, node.tail, *node.attrib.values()):
            if text is None:
                continue
            for character in text:
                code = ord(character)
                if not (character in "\t\n\r" or 0x20 <= code <= 0xD7FF
                        or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF):
                    raise ValueError(
                        f"Source contains U+{code:04X}, which C-USX XML cannot represent "
                        "without changing the text. Remove or replace that control "
                        "character in a copy of the source, or try another format"
                    )
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # XML parsers normalize literal CR in text. Character references preserve
    # the source scalar instead, including CR decoded from XHTML entities.
    return data if profile == LEGACY_PROFILE else data.replace(b"\r", b"&#13;")


def convert_to_cusx(
    source: Path,
    output: Path,
    *,
    source_format: SourceFormat,
    name: str,
    description: str = "",
    author_sub: str | None = None,
    category: str = "",
) -> Path:
    from .cusx_package import write_package

    parser = PARSERS.get(source_format)
    if parser is None:
        raise ValueError("C-USX currently supports EPUB, PDF, HTML, XML/TEI and plain text sources")
    return write_package(
        source,
        output,
        source_format=source_format,
        name=name,
        description=description,
        author_sub=author_sub,
        category=category,
    )


def validate_cusx_archive(path: Path) -> dict[str, Any]:
    """Integrity/profile checks, not upstream USX or corpus-document conformance."""
    reasons: list[str] = []
    stats: dict[str, int] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("duplicate package members")
            if sum(info.file_size for info in infos) > MAX_BYTES:
                raise ValueError("C-USX package exceeds the uncompressed size limit")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest["format"] == PROFILE:
                from .cusx_package import validate_package

                return validate_package(path)
            if set(names) != MEMBERS | {"manifest.json"}:
                raise ValueError("unexpected or missing package members")
            if manifest["format"] != LEGACY_PROFILE or set(manifest["files"]) != MEMBERS:
                raise ValueError("unsupported C-USX package profile or file inventory")
            members = {name: archive.read(name) for name in MEMBERS}
            if any(digest(data) != manifest["files"][name] for name, data in members.items()):
                raise ValueError("C-USX member checksum mismatch")
            xml = members["document.usx"]
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise ValueError("XML entity declarations are unsupported")
            root = ET.fromstring(xml)
            if root.tag != "usx" or root.get(f"{{{CX}}}profile") != LEGACY_PROFILE:
                raise ValueError("invalid C-USX document profile")
            document = Document.model_validate_json(members["document.json"])
            if document_xml(document, profile=LEGACY_PROFILE) != xml:
                raise ValueError("C-USX XML differs from the parsed document projection")
            validated_snapshot = TextSnapshot.model_validate_json(members["snapshot.json"])
            snapshot = validated_snapshot.model_dump(mode="json")
            if snapshot["endpoint"] != manifest["identity"] or snapshot["endpoint"][
                "revision"
            ] != digest(xml):
                raise ValueError("snapshot document identity or revision mismatch")
            if snapshot["stream_id"] != STREAM or snapshot["text"] != "".join(root.itertext()):
                raise ValueError("snapshot text differs from the C-USX stream")
            if manifest["stream"] != {
                "id": STREAM,
                "offset_unit": "unicode-scalar",
                "normalization": "preserve",
            }:
                raise ValueError("unsupported text stream conventions")
            if json.loads(members["references.json"]) != []:
                raise ValueError("conversion profile cannot claim approved reference publication")
            mappings = json.loads(members["mappings.json"])
            if not isinstance(mappings, dict) or mappings.get("mappings") != []:
                raise ValueError("conversion profile cannot claim native mapping evidence")
            stats = {
                "documents": 1,
                "characters": len(snapshot["text"]),
                "units": sum(1 for e in root.iter() if e.tag == f"{{{CX}}}unit"),
            }
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
        reasons.append(str(exc))
    return {
        "corpus": path.stem,
        "valid": not reasons,
        "stats": stats,
        "reasons": reasons,
        "checks": {"cusx_package_integrity": not reasons},
    }
