"""Versioned C-USX ZIP projection of the existing parsed document tree.

This profile preserves the parser output, not a full USX scripture or graph
projection. It never invents scripture identities or original-file anchors.
"""

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from corpora_linking import TextSnapshot

from ..parsers import PARSERS
from ..parsers.schema import Document, SourceFormat, Unit

CX = "urn:corpora:usx-extension:0.1"
PROFILE = "corpora-cusx-package/0.1.0"
STREAM = "cusx-itertext/v1"
MAX_BYTES = 256 * 1024 * 1024
MEMBERS = {"document.usx", "document.json", "snapshot.json", "references.json", "mappings.json"}
ET.register_namespace("cx", CX)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _unit(parent: ET.Element, unit: Unit, depth: int = 0) -> None:
    if depth > 200:
        raise ValueError("source structure exceeds the supported nesting depth")
    # Source IDs remain source metadata; they do not become global anchors.
    node = ET.SubElement(parent, f"{{{CX}}}unit", {"type": unit.type})
    node.set("attributes", encoded(unit.attrs).decode())
    if unit.id is not None:
        node.set("source-id", unit.id)
    if unit.label is not None:
        node.set("label", unit.label)
    if unit.tokens:
        para = ET.SubElement(node, "para", {"style": "p"})
        para.text = "".join(token.text + token.after for token in unit.tokens)
    for child in unit.children:
        _unit(node, child, depth + 1)
    if unit.tokens and not unit.children:
        # Deliberate converted-stream separator, never a native-file offset.
        node.tail = "\n\n"


def document_xml(document: Document) -> bytes:
    root = ET.Element("usx", {"version": "3.1", f"{{{CX}}}profile": PROFILE})
    for unit in document.units:
        _unit(root, unit)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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
    parser = PARSERS.get(source_format)
    if parser is None:
        raise ValueError("C-USX currently supports EPUB, PDF, HTML, XML/TEI and plain text sources")
    if source_format == SourceFormat.PDF:
        from pypdf import PdfReader

        # Do not produce a partial document while silently skipping OCR pages.
        pages = PdfReader(source).pages
        if not pages or any(not (page.extract_text() or "").strip() for page in pages):
            raise ValueError("C-USX requires extractable text on every PDF page; OCR is required")
    document = parser.parse(str(source))
    if not document.units:
        raise ValueError("source contains no supported document units")
    xml = document_xml(document)
    root = ET.fromstring(xml)
    text = "".join(root.itertext())
    if not text.strip():
        raise ValueError("source contains no extractable text")
    source_digest = digest(source.read_bytes())
    conversion_id = str(uuid.uuid4())
    endpoint = {
        "work_id": "urn:uuid:" + str(uuid.uuid4()),
        "edition_id": "urn:uuid:" + str(uuid.uuid4()),
        "package_id": "urn:uuid:" + conversion_id,
        "revision": digest(xml),
        "document_id": "document.usx",
        "locators": [],
    }
    members = {
        "document.usx": xml,
        "document.json": encoded(document.model_dump(mode="json")),
        "snapshot.json": encoded({"endpoint": endpoint, "stream_id": STREAM, "text": text}),
        "references.json": encoded([]),
        "mappings.json": encoded(
            {"mappings": [], "diagnostics": ["native selection mappings unavailable"]}
        ),
    }
    manifest = {
        "format": PROFILE,
        "name": name,
        "description": description,
        "category": category,
        "created_by": author_sub,
        "identity": endpoint,
        "source": {
            "filename": source.name,
            "format": source_format.value,
            "revision": source_digest,
        },
        "stream": {"id": STREAM, "offset_unit": "unicode-scalar", "normalization": "preserve"},
        "diagnostics": [
            "parser projection; source structure and spacing may differ",
            "no references approved or published",
        ],
        "files": {key: digest(data) for key, data in members.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", encoded(manifest))
            for key, data in members.items():
                archive.writestr(key, data)
        summary = validate_cusx_archive(temporary)
        if not summary["valid"]:
            raise ValueError("converted C-USX package failed validation")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def validate_cusx_archive(path: Path) -> dict[str, Any]:
    """Integrity/profile checks, not upstream USX or corpus-document conformance."""
    reasons: list[str] = []
    stats: dict[str, int] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != MEMBERS | {"manifest.json"}:
                raise ValueError("unexpected, duplicate or missing package members")
            if sum(info.file_size for info in infos) > MAX_BYTES:
                raise ValueError("C-USX package exceeds the uncompressed size limit")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest["format"] != PROFILE or set(manifest["files"]) != MEMBERS:
                raise ValueError("unsupported C-USX package profile or file inventory")
            members = {name: archive.read(name) for name in MEMBERS}
            if any(digest(data) != manifest["files"][name] for name, data in members.items()):
                raise ValueError("C-USX member checksum mismatch")
            xml = members["document.usx"]
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise ValueError("XML entity declarations are unsupported")
            root = ET.fromstring(xml)
            if root.tag != "usx" or root.get(f"{{{CX}}}profile") != PROFILE:
                raise ValueError("invalid C-USX document profile")
            document = Document.model_validate_json(members["document.json"])
            if document_xml(document) != xml:
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
