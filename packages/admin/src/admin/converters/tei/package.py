"""Owned .ctei ZIP contract, metadata, evidence and independent archive checks."""

from __future__ import annotations

import importlib
import json
import lzma
import mimetypes
import os
import shutil
import tempfile
import uuid
import zipfile
import zlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Lock
from urllib.parse import urlsplit

import yaml
from lxml import etree

from ...parsers.schema import CorpusCategory, SourceFormat
from ..convert_to_corpus import _build_history, _build_manifest
from .encoding import NS, XML, T, convert_model, digest, header, validators, xml
from .inputs import load_source, readable

VERSION_DIR = "version_1.0.0"
CTEI_NS = "urn:corpora:ctei:1"
_ZIP_DECODE_ERRORS: tuple[type[Exception], ...] = (zlib.error, lzma.LZMAError)
try:
    _zstd = importlib.import_module("compression.zstd")
except ModuleNotFoundError:
    pass
else:
    _ZIP_DECODE_ERRORS += (_zstd.ZstdError,)
REQUIRED = {
    "manifest.yml",
    "toc.yml",
    "review.xml",
    "references.xml",
    "history.xml",
    "assets/mapping.xml",
    "presentations/styles.xml",
    "assets/conversion/receipt.json",
}
_SCHEMA_LOCK = Lock()


def _write_xml(path, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(etree.tostring(root, encoding="utf-8", xml_declaration=True))


def history_xml(history: dict) -> bytes:
    root = etree.Element(f"{{{CTEI_NS}}}history", nsmap={None: CTEI_NS})
    for row in history["versions"]:
        version = etree.SubElement(root, f"{{{CTEI_NS}}}version")
        for field in ("id", "label", "title", "at", "current", "snapshot_key"):
            value = row.get(field)
            if value is not None:
                version.set(field, str(value).lower() if isinstance(value, bool) else str(value))
        for field in ("author", "approved_by"):
            actor = row.get(field)
            if actor:
                etree.SubElement(version, f"{{{CTEI_NS}}}{field}", sub=actor["sub"])
        for item in row.get("files", []):
            etree.SubElement(version, f"{{{CTEI_NS}}}file", **item)
        for note in row.get("notes", []):
            etree.SubElement(version, f"{{{CTEI_NS}}}note").text = str(note)
    return etree.tostring(root, encoding="utf-8", xml_declaration=True)


def read_history(data: bytes) -> dict:
    root = xml(data)
    if root.tag != f"{{{CTEI_NS}}}history" or not len(root):
        raise ValueError("CTEI history.xml has no version records")
    versions = []
    for version in root:
        if version.tag != f"{{{CTEI_NS}}}version" or version.get("current") not in {
            "true",
            "false",
        }:
            raise ValueError("Invalid CTEI history version")
        row = {key: version.get(key) for key in ("id", "label", "title", "at", "snapshot_key")}
        if not all(row[k] for k in ("id", "label", "title", "at")):
            raise ValueError("Incomplete CTEI history version")
        row["current"] = version.get("current") == "true"
        for field in ("author", "approved_by"):
            actor = version.find(f"{{{CTEI_NS}}}{field}")
            row[field] = {"sub": actor.get("sub")} if actor is not None else None
        row["files"] = [dict(e.attrib) for e in version.findall(f"{{{CTEI_NS}}}file")]
        row["notes"] = [e.text or "" for e in version.findall(f"{{{CTEI_NS}}}note")]
        versions.append(row)
    if sum(v["current"] for v in versions) != 1:
        raise ValueError("CTEI history requires exactly one current version")
    return {"versions": versions}


def _category(model, requested):
    nodes = []

    def visit(n):
        nodes.append(n)
        for child in n.get("children", []):
            visit(child)

    for region in ("front", "body", "back"):
        for n in model.get(region, []):
            visit(n)
    types = {n.get("attrs", {}).get("type") for n in nodes}
    if "surah" in types or model.get("citations"):
        return "canon"
    if model["work"]["kind"] == "paper":
        return "papers"
    if (
        requested == CorpusCategory.BOOK
        or types & {"chapter", "part", "book"}
        or sum(n["tag"] == "div" for n in model["body"]) > 1
    ):
        return "book"
    return "document"


def convert_to_ctei(
    source_path: Path,
    output_path: Path,
    *,
    source_format: SourceFormat,
    name: str = "",
    description: str = "",
    category: CorpusCategory | None = None,
    author_sub: str | None = None,
) -> Path:
    """Build and validate before atomically exposing an owned CTEI archive."""
    if output_path.suffix != ".ctei":
        raise ValueError("CTEI output must use the .ctei extension")
    model, source_assets, evidence, metadata = load_source(source_path, source_format, name)
    if "sourceAssetHashes" in evidence:
        evidence["sourceAssetHashes"] = sorted({digest(b) for b in source_assets.values()})
    title = model["work"]["title"]
    uid = model["work"]["id"]
    written = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="corpora-ctei-") as scratch:
        temporary = Path(scratch)
        reading = temporary / "reading"
        with _SCHEMA_LOCK:
            convert_model(source_path, reading, model, source_assets, evidence)
        index = json.loads((reading / "index.json").read_bytes())
        root = temporary / "archive"
        (root / VERSION_DIR).mkdir(parents=True)
        if (reading / "assets").exists():
            shutil.copytree(reading / "assets", root / "assets")
        assets = root / "assets"
        (assets / "conversion").mkdir(parents=True, exist_ok=True)
        (assets / "source").mkdir()
        shutil.copyfile(source_path, assets / "source" / ("original" + source_path.suffix.lower()))
        (assets / "conversion" / "metadata.json").write_text(
            metadata.model_dump_json(indent=2), encoding="utf-8"
        )
        (assets / "conversion" / "evidence.json").write_text(
            json.dumps(index["evidence"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.copyfile(
            reading / "source-ledger.json", assets / "conversion" / "source-ledger.json"
        )
        refs = etree.Element(f"{{{CTEI_NS}}}references", nsmap={None: CTEI_NS})
        mapping = etree.Element(f"{{{CTEI_NS}}}mapping", nsmap={None: CTEI_NS})
        styles = etree.Element(f"{{{CTEI_NS}}}styles", nsmap={None: CTEI_NS})
        review = etree.Element(
            f"{{{NS}}}TEI",
            nsmap={None: NS},
            attrib={f"{{{XML}}}id": "review", f"{{{XML}}}lang": model["work"]["language"]},
        )
        header(
            review, model["work"], title + " — conversion review", digest(source_path.read_bytes())
        )
        stand_off = etree.SubElement(review, f"{{{NS}}}standOff")
        categories = etree.SubElement(stand_off, f"{{{NS}}}interpGrp", type="status")
        etree.SubElement(
            categories, f"{{{NS}}}interp", attrib={f"{{{XML}}}id": "pending"}
        ).text = "Requires human validation"
        annotations = etree.SubElement(stand_off, f"{{{NS}}}listAnnotation")
        review_count = 0
        kinds = set()

        def finding(target, message, kind):
            nonlocal review_count
            review_count += 1
            if kind not in kinds:
                etree.SubElement(
                    categories, f"{{{NS}}}interp", attrib={f"{{{XML}}}id": kind}
                ).text = kind
                kinds.add(kind)
            annotation = etree.SubElement(
                annotations,
                f"{{{NS}}}annotation",
                attrib={
                    f"{{{XML}}}id": f"r{review_count:05d}",
                    "target": target,
                    "ana": "#pending #" + kind,
                },
            )
            etree.SubElement(
                etree.SubElement(annotation, f"{{{NS}}}note"), f"{{{NS}}}p"
            ).text = message

        docs = []
        presentations: dict[str, list[str]] = {}
        for document in index["documents"]:
            path = VERSION_DIR + "/" + Path(document["path"]).name
            tei = xml((reading / document["path"]).read_bytes())
            docs.append({**document, "path": path})
            for element in tei.xpath("t:text//*[@xml:id]", namespaces=T):
                local = etree.QName(element).localname
                target = path + "#" + element.get(f"{{{XML}}}id")
                semantic = {
                    "p": "paragraph",
                    "head": "heading",
                    "table": "table",
                    "note": "note",
                    "figure": "figure",
                    "list": "list",
                    "lg": "poetry",
                }.get(local)
                if semantic:
                    if local == "head":
                        depth = len(element.xpath("ancestor::t:div", namespaces=T))
                        semantic = (
                            "caption"
                            if element.xpath("ancestor::t:figure|ancestor::t:table", namespaces=T)
                            else "h" + str(min(max(depth, 1), 6))
                        )
                    presentations.setdefault(semantic, []).append(target)
                if local in {"gap", "unclear"}:
                    finding(
                        target,
                        "Source marks uncertain text: " + (element.get("reason") or "unspecified"),
                        "source-uncertainty",
                    )
                if local == "ref":
                    destination = element.get("target", "")
                    parts = urlsplit(destination)
                    status = (
                        "resolved"
                        if element.get("type") == "resolved"
                        else "external-unvalidated"
                        if parts.scheme in {"http", "https", "mailto"}
                        else "unresolved"
                    )
                    absolute = (
                        VERSION_DIR + "/" + (parts.path or Path(path).name) + "#" + parts.fragment
                        if status == "resolved"
                        else destination
                    )
                    entry = etree.SubElement(
                        refs,
                        f"{{{CTEI_NS}}}reference",
                        id=f"ref{len(refs) + 1:05d}",
                        source=target,
                        target=absolute,
                        status=status,
                        kind="citation" if destination.startswith("urn:source-osis:") else "link",
                    )
                    entry.text = "".join(element.itertext())
                    if status != "resolved":
                        finding(
                            target,
                            "Reference destination requires validation: " + destination,
                            "reference",
                        )
                if local == "graphic":
                    asset_path = element.get("url", "").removeprefix("../")
                    etree.SubElement(
                        mapping,
                        f"{{{CTEI_NS}}}asset",
                        path=asset_path,
                        target=target,
                        placement="inline",
                    )
            warnings = index["evidence"].get("warnings", [])
            for warning in warnings:
                finding(path + "#" + document["id"], str(warning), "extraction")
            if source_format == SourceFormat.PDF:
                finding(
                    path + "#" + document["id"],
                    "Every extracted PDF region requires independent visual collation, including scripts, diacritics, notes and tables",
                    "source-verification",
                )
            _write_xml(root / path, tei)
        # Native TEI requires a non-empty listAnnotation; empty review uses no list.
        if not review_count:
            stand_off.remove(annotations)
        for semantic, targets in sorted(presentations.items()):
            etree.SubElement(
                styles, f"{{{CTEI_NS}}}style", semantic=semantic, targets=" ".join(targets)
            )
        registered = {e.get("path") for e in mapping}
        for asset_path in sorted(assets.rglob("*")):
            if asset_path.is_file() and asset_path.relative_to(root).as_posix() not in registered:
                etree.SubElement(
                    mapping,
                    f"{{{CTEI_NS}}}asset",
                    path=asset_path.relative_to(root).as_posix(),
                    placement="supplementary",
                )
        for supplemental in ("assets/mapping.xml", "assets/conversion/receipt.json"):
            etree.SubElement(
                mapping, f"{{{CTEI_NS}}}asset", path=supplemental, placement="supplementary"
            )
        _write_xml(assets / "mapping.xml", mapping)
        _write_xml(root / "presentations/styles.xml", styles)
        _write_xml(root / "review.xml", review)
        _write_xml(root / "references.xml", refs)
        resolved_category = _category(model, category)
        summary = readable(description) or readable(metadata.description)
        if not summary:
            creators = ", ".join(metadata.creators)
            subject = "; ".join(metadata.subjects)
            summary = (
                f"A {resolved_category}"
                + (f" by {creators}" if creators else "")
                + (f" covering {subject}" if subject else "")
                + (f", published by {metadata.publisher}" if metadata.publisher else "")
                + "."
            )
        manifest = _build_manifest(
            uid=uid,
            name=title,
            description=summary,
            version="1.0.0",
            language=metadata.extra["languageName"],
            language_code=metadata.extra["languageCode"],
            corpus_type="tei",
            category=resolved_category,
            written_date=written,
            dataset_id="",
            project_id="",
            assets=[],
            thumbnail=None,
        )
        manifest["assets"] = [
            _asset_entry(p, assets) for p in sorted(assets.rglob("*")) if p.is_file()
        ]
        # Receipt is registered before writing it; it inventories every other member.
        manifest["assets"].append(_asset_entry(assets / "conversion/receipt.json", assets))
        (root / "manifest.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        toc = {
            "uid": uid,
            "version": "1.0.0",
            "corpusId": uid,
            "has_sections": any(n.get("tag") == "div" for n in index["hierarchy"]["body"]),
            "has_features": False,
            "has_nodes": True,
            "files": [
                {
                    "id": d["id"],
                    "path": d["path"],
                    "type": "text",
                    "name": d["title"],
                    "visible": True,
                }
                for d in docs
            ],
            "total_file_count": len(docs),
            "total_file_size": sum((root / d["path"]).stat().st_size for d in docs),
            "publisherId": metadata.publisher or "",
            "authorId": metadata.creators,
            "readingOrder": [d["path"] for d in docs],
            "hierarchy": _remap_hierarchy(index["hierarchy"]),
        }
        (root / "toc.yml").write_text(
            yaml.safe_dump(toc, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        history = _build_history(written_date=written, author_sub=author_sub)
        history["versions"][0]["files"] = [
            {"path": p.relative_to(root).as_posix(), "kind": "added"}
            for p in sorted(root.rglob("*"))
            if p.is_file()
        ] + [
            {"path": "history.xml", "kind": "added"},
            {"path": "assets/conversion/receipt.json", "kind": "added"},
        ]
        (root / "history.xml").write_bytes(history_xml(history))
        receipt = {
            "profile": index["profile"],
            "sourceSha256": index["sourceSha256"],
            "reviewItems": review_count,
            "files": {
                p.relative_to(root).as_posix(): digest(p.read_bytes())
                for p in sorted(root.rglob("*"))
                if p.is_file()
            },
        }
        (assets / "conversion/receipt.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )
        archive = temporary / "result.ctei"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for member_path in sorted(root.rglob("*")):
                zf.write(member_path, member_path.relative_to(root).as_posix())
        validate_ctei_archive(archive)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise ValueError("CTEI output already exists")
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, suffix=".ctei", delete=False
        ) as dest:
            pending = Path(dest.name)
        try:
            shutil.copyfile(archive, pending)
            os.link(pending, output_path)
        finally:
            pending.unlink(missing_ok=True)
    return output_path


def _asset_entry(path, assets):
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "id": str(uuid.uuid4()),
        "path": path.relative_to(assets).as_posix(),
        "type": mime.split("/")[0],
        "name": path.stem,
        "visible": True,
    }


def _remap_hierarchy(value):
    if isinstance(value, dict):
        return {
            k: VERSION_DIR + "/" + Path(v).name if k == "document" else _remap_hierarchy(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_remap_hierarchy(v) for v in value]
    return value


class CTEIArchiveValidationError(ValueError):
    """The supplied archive is malformed or fails its declared package contract."""


def validate_ctei_archive(path: Path) -> dict:
    """Validate input structure while keeping schema/operational failures distinct."""
    with _SCHEMA_LOCK:
        schemas = validators()
    try:
        return _validate_ctei_archive(path, schemas)
    except (ValueError, zipfile.BadZipFile, zlib.error, etree.XMLSyntaxError, yaml.YAMLError) as exc:
        raise CTEIArchiveValidationError(str(exc)) from exc
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise CTEIArchiveValidationError("Invalid CTEI archive structure") from exc


def _validate_ctei_archive(path: Path, schemas: tuple) -> dict:
    """Check ZIP paths, layout, manifest inventory, TEI schemas and all local pointers."""
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if any(info.flag_bits & 1 for info in infos):
            raise ValueError("Encrypted CTEI ZIP members are not supported")
        names = [i.filename for i in infos]
        if (
            len(names) != len(set(names))
            or len(infos) > 25000
            or sum(i.file_size for i in infos) > 2 * 1024**3
        ):
            raise ValueError("Unsafe or oversized CTEI ZIP inventory")
        for name in names:
            if (
                PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or "\\" in name
            ):
                raise ValueError("CTEI member escapes archive")
        try:
            if not REQUIRED <= set(names) or zf.testzip() is not None:
                raise ValueError("CTEI ZIP is incomplete or corrupt")
            files = {n: zf.read(n) for n in names if not n.endswith("/")}
        except NotImplementedError as exc:
            raise ValueError("Unsupported CTEI ZIP compression") from exc
        except _ZIP_DECODE_ERRORS as exc:
            raise ValueError("Corrupt CTEI compressed data") from exc
        except OSError as exc:
            # bz2 uses this specific errno-free error for malformed compressed input.
            # Other I/O failures must remain operational errors.
            if exc.errno is None and str(exc) == "Invalid data stream":
                raise ValueError("Corrupt CTEI BZIP2 data") from exc
            raise
    manifest = yaml.safe_load(files["manifest.yml"])
    toc = yaml.safe_load(files["toc.yml"])
    if (
        uuid.UUID(manifest["uid"]).version != 4
        or manifest.get("format") != "corpus"
        or manifest.get("format_version") != "1"
        or manifest.get("tocFile") != "toc.yml"
    ):
        raise ValueError("Invalid CTEI manifest identity or format")
    if manifest["uid"] != toc["uid"] or manifest["version"] != toc["version"]:
        raise ValueError("CTEI manifest/TOC identity mismatch")
    assets = {n.removeprefix("assets/") for n in files if n.startswith("assets/")}
    inventory = [a["path"] for a in manifest["assets"]]
    if set(inventory) != assets or len(inventory) != len(assets):
        raise ValueError("CTEI manifest does not register every asset exactly once")
    receipt = json.loads(files["assets/conversion/receipt.json"])
    expected = {n: digest(b) for n, b in files.items() if n != "assets/conversion/receipt.json"}
    if receipt["files"] != expected:
        raise ValueError("CTEI member hashes do not match conversion evidence")
    docs = toc.get("readingOrder", [])
    if not docs or len(docs) != len(set(docs)) or docs != [d["path"] for d in toc["files"]]:
        raise ValueError("Invalid CTEI reading order")
    if set(docs) != {n for n in files if re_document(n)}:
        raise ValueError("CTEI TOC does not register all reading documents")
    roots = {
        n: xml(b)
        for n, b in files.items()
        if n.endswith(".xml") and not n.startswith("assets/source")
    }
    ids = {
        (n, e.get(f"{{{XML}}}id"))
        for n, root in roots.items()
        for e in root.iter()
        if e.get(f"{{{XML}}}id")
    }

    def local_target(target):
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or (parts.path, parts.fragment) not in ids:
            raise ValueError("CTEI sidecar has a missing or non-local target")

    with _SCHEMA_LOCK:
        upstream, profile, schematron = schemas
        for name in docs:
            root = roots[name]
            for schema in (upstream, profile, schematron):
                if not schema.validate(root):
                    raise ValueError("CTEI reading document fails TEI schema: " + name)
            for ref in root.xpath("//t:ref[@type='resolved']", namespaces=T):
                parts = urlsplit(ref.get("target"))
                local_target(
                    str(PurePosixPath(name).parent / (parts.path or PurePosixPath(name).name))
                    + "#"
                    + parts.fragment
                )
            for graphic in root.xpath("//t:graphic", namespaces=T):
                asset = graphic.get("url", "").removeprefix("../")
                if asset not in files or not asset.startswith("assets/"):
                    raise ValueError("CTEI graphic has no registered asset")
        if not upstream.validate(roots["review.xml"]):
            raise ValueError("CTEI review.xml fails TEI P5 schema")
    for annotation in roots["review.xml"].xpath("//t:annotation", namespaces=T):
        for target in annotation.get("target", "").split():
            local_target(target)
    for reference in roots["references.xml"]:
        local_target(reference.get("source", ""))
        if reference.get("status") == "resolved":
            local_target(reference.get("target", ""))
    for asset in roots["assets/mapping.xml"]:
        if asset.get("path") not in files:
            raise ValueError("CTEI mapping names a missing asset")
        if asset.get("target"):
            local_target(asset.get("target"))
    for style in roots["presentations/styles.xml"]:
        if set(style.attrib) != {"semantic", "targets"} or style.tag != f"{{{CTEI_NS}}}style":
            raise ValueError("CTEI presentations must contain semantic roles only")
        if style.get("semantic") not in {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "paragraph",
            "table",
            "note",
            "figure",
            "caption",
            "list",
            "poetry",
        }:
            raise ValueError("CTEI presentations contain an unsupported semantic role")
        for target in style.get("targets", "").split():
            local_target(target)
    read_history(files["history.xml"])
    count = len(roots["review.xml"].xpath("//t:annotation", namespaces=T))
    return {
        "corpus": manifest["name"],
        "valid": True,
        "stats": {"documents": len(docs), "assets": len(assets), "review_items": count},
        "reasons": [],
        "checks": [
            "archive",
            "metadata",
            "assets",
            "hashes",
            "tei-p5",
            "profile",
            "references",
            "review",
            "history",
        ],
        "source_verified": False,
    }


def re_document(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) == 2 and parts[0].startswith("version_") and parts[1].endswith(".xml")
