"""EPUB -> Text-Fabric -> validated Corpora USX 0.1.0 ZIP (.cusx)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from lxml import etree as etree
from tf.fabric import Fabric

from ..parsers.schema import CorpusCategory
from ._cusx_export import export
from ._cusx_source import read_publication
from ._walker import SectionSpec, convert_documents
from .cusx.validate_package import validate_package as _validate_package
from .cusx.validate_xml import load, require


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:96]


def validate_package(folder: Path) -> dict:
    """Apply the draft checks plus manifested image-reference validation."""
    from urllib.parse import unquote, urlsplit

    stats = _validate_package(folder)
    folder = folder.resolve()
    metadata = load(folder / "metadata.xml").getroot()
    resources = {(folder / e.get("uri")).resolve() for e in metadata.findall("manifest/resource")}
    for entry in metadata.findall("source/structure//content"):
        path = folder / entry.get("src")
        for figure in load(path).getroot().iter("figure"):
            parts = urlsplit(figure.get("file"))
            target = (path.parent / unquote(parts.path)).resolve()
            require(
                not parts.scheme and not parts.netloc and not parts.query and target in resources,
                "PKG-010",
                "Images must select manifested publication assets",
            )
    return stats


def validate_cusx(archive: str | Path) -> dict:
    """Validate archive paths, resources, content grammar, links and JSON parity."""
    with (
        zipfile.ZipFile(archive) as zipped,
        tempfile.TemporaryDirectory(prefix="cusx-check-") as tmp,
    ):
        folder = Path(tmp).resolve()
        members = zipped.infolist()
        if len(members) > 10000 or sum(m.file_size for m in members) > 512 * 1024 * 1024:
            raise ValueError("CUSX exceeds the expanded resource limit")
        if len({m.filename for m in members}) != len(members):
            raise ValueError("Duplicate CUSX archive paths")
        for member in members:
            target = (folder / member.filename).resolve()
            if (
                not target.is_relative_to(folder)
                or member.filename.startswith("/")
                or "\\" in member.filename
            ):
                raise ValueError("CUSX resource escapes the archive")
            if member.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("CUSX symlinks are unsupported")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        return {"valid": True, "stats": validate_package(folder), "reasons": []}


def convert_epub_to_usx(
    source: str | Path,
    output: str | Path | None = None,
    *,
    output_path_for: Callable[[str], Path] | None = None,
    work_dir: str | Path | None = None,
    name: str = "",
    evidence_path: str | Path | None = None,
    on_log: Callable[[str], None] = lambda _: None,
    on_display_name: Callable[[str], None] = lambda _: None,
    on_validation: Callable[[dict], None] = lambda _: None,
) -> Path:
    """Write a .cusx ZIP atomically after full validation.

    Bibliography, presentation and logical content belong to the package.
    Import paths, original styles, TF identities and diagnostics are recorded
    in a separate conversion_metadata SQLite table beside the archive (or at
    evidence_path). Intermediate TF data is private temporary scratch space.
    Unsupported structures fail rather than ship silently flattened content.
    """
    source = Path(source).expanduser()
    if not source.is_file():
        raise ValueError("EPUB source file not found")
    on_log("Parsing source...")
    try:
        publication = read_publication(source)
    except (KeyError, IndexError, zipfile.BadZipFile, etree.XMLSyntaxError, UnicodeError) as exc:
        raise ValueError("Invalid or incomplete EPUB publication") from exc
    title = publication.document.metadata.title or name or source.stem
    on_display_name(title)
    if output_path_for is not None:
        destination = Path(output_path_for(title))
    elif output is not None:
        destination = Path(output).expanduser()
    else:
        destination = Path.cwd() / ((_slug(title) or "book") + ".cusx")
    if destination.suffix.lower() != ".cusx":
        raise ValueError("EPUB-to-USX output must use the .cusx extension")
    evidence = (
        Path(evidence_path)
        if evidence_path
        else destination.with_suffix(".conversion-metadata.sqlite")
    )
    if destination.resolve() == source.resolve() or evidence.resolve() in {
        source.resolve(),
        destination.resolve(),
    }:
        raise ValueError("Conversion destinations must be distinct from the source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="epub-usx-", dir=work_dir) as tmp:
        scratch = Path(tmp)
        tf_dir = scratch / "text-fabric"
        on_log("Building Text-Fabric dataset...")
        convert_documents(
            [publication.document],
            tf_dir,
            root_type="book",
            otype_for=lambda u: (
                "chapter" if u.type == "chapter" else "paragraph" if u.type == "p" else "element"
            ),
            format_value="epub",
            source_label=str(source),
            section_spec=SectionSpec(types=("book", "chapter"), features=("title", "label")),
            category=CorpusCategory.BOOK,
        )
        features = [
            p.stem
            for p in tf_dir.glob("*.tf")
            if p.is_file() and p.stem not in {"otext", "otype", "oslots"}
        ]
        api = Fabric(locations=str(tf_dir), silent="deep").load(" ".join(features), silent="deep")
        if api is None:
            raise ValueError("Text-Fabric dataset could not be loaded")
        text = "".join(
            (api.F.text.v(n) or "") + (api.F.after.v(n) or "") for n in api.F.otype.s("word")
        )
        if text != "".join(publication.texts):
            raise ValueError("EPUB reading-order text differs from Text-Fabric")
        work_id = _slug(title) or "book"
        on_log("Building Corpora USX package...")
        record = export(publication, tf_dir, scratch / "package", work_id, title)
        record["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        record["source_path"] = str(source.resolve())
        record["source_format"] = "epub"
        record["exact_source_tf_text_match"] = True
        record["corpora_version"] = "0.1.0"
        if record["style_diagnostics"]:
            on_log(
                f"CSS conversion diagnostics: {len(record['style_diagnostics'])}; saved in conversion metadata."
            )
        on_log("Validating Corpora USX package...")
        stats = validate_package(scratch / "package")
        summary = {
            "valid": True,
            "stats": stats,
            "reasons": [],
            "checks": {
                "exact_source_tf_text_match": True,
                "non_whitespace_text_match": True,
                "grammar": True,
                "manifest": True,
                "links": True,
                "json_xml_parity": True,
            },
        }
        # Create beside the destination so os.replace stays on one filesystem.
        fd, pending = tempfile.mkstemp(prefix=".cusx-", dir=destination.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted((scratch / "package").rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(scratch / "package").as_posix())
            validate_cusx(pending)
            root = etree.Element("conversionMetadata", documentId=work_id, version="1")
            etree.SubElement(
                root,
                "source",
                format="epub",
                path=record["source_path"],
                sha256=record["source_sha256"],
            )
            etree.SubElement(root, "evidence", encoding="json").text = json.dumps(
                record, ensure_ascii=False
            )
            evidence.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(evidence) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS conversion_metadata (document_id TEXT PRIMARY KEY, source_format TEXT NOT NULL, source_sha256 TEXT NOT NULL, metadata_xml BLOB NOT NULL)"
                )
                db.execute(
                    "INSERT OR REPLACE INTO conversion_metadata VALUES(?,?,?,?)",
                    (
                        work_id,
                        "epub",
                        record["source_sha256"],
                        etree.tostring(root, encoding="UTF-8", xml_declaration=True),
                    ),
                )
            os.replace(pending, destination)
        finally:
            Path(pending).unlink(missing_ok=True)
        on_validation(summary)
    on_log("Conversion complete.")
    return destination
