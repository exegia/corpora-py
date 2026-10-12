"""Source adapters for CTEI. Unsupported semantics are rejected, never dropped."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from lxml import etree
from pypdf import PdfReader

from ...parsers import PARSERS
from ...parsers.schema import DocumentMetadata, SourceFormat
from .encoding import DIV_TYPES, NS, XML, local_path, node, xml
from .sources import (
    HtmlMapper,
    archive_bytes,
    conform_divisions,
    epub_source,
    html_root,
    normalized,
    raw_reading,
    source_coverage,
    structured_blocks,
    tag,
)

LANGUAGES = {
    "en": ("english", "ENG"),
    "eng": ("english", "ENG"),
    "fr": ("french", "FRA"),
    "fra": ("french", "FRA"),
    "fre": ("french", "FRA"),
    "de": ("german", "DEU"),
    "deu": ("german", "DEU"),
    "ger": ("german", "DEU"),
    "he": ("hebrew", "HEB"),
    "heb": ("hebrew", "HEB"),
    "grc": ("ancient greek", "GRC"),
    "el": ("greek", "ELL"),
    "ell": ("greek", "ELL"),
    "la": ("latin", "LAT"),
    "lat": ("latin", "LAT"),
    "ar": ("arabic", "ARA"),
    "ara": ("arabic", "ARA"),
    "es": ("spanish", "SPA"),
    "spa": ("spanish", "SPA"),
    "it": ("italian", "ITA"),
    "ita": ("italian", "ITA"),
    "pt": ("portuguese", "POR"),
    "por": ("portuguese", "POR"),
    "ru": ("russian", "RUS"),
    "rus": ("russian", "RUS"),
    "zh": ("chinese", "ZHO"),
    "zho": ("chinese", "ZHO"),
    "ja": ("japanese", "JPN"),
    "jpn": ("japanese", "JPN"),
    "ko": ("korean", "KOR"),
    "kor": ("korean", "KOR"),
    "nl": ("dutch", "NLD"),
    "nld": ("dutch", "NLD"),
}


def language_metadata(value: str | None, text: str) -> tuple[str, str, str]:
    """Use source language metadata, with the requested English default."""
    code = (value or "").strip().lower().replace("_", "-")
    code = next((ident for ident, pair in LANGUAGES.items() if pair[0] == code), code)
    code = code or "en"
    base = code.split("-")[0]
    name, iso = LANGUAGES.get(base, (base, base.upper()))
    return name, iso, code


def readable(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("_", " ")).strip()


def load_source(source: Path, source_format: SourceFormat, name: str):
    if source_format == SourceFormat.EPUB:
        # Check paths/expanded size before the metadata library reads archive contents.
        archive_bytes(source)
    metadata = (
        PARSERS[source_format].parse_metadata(str(source))
        if source_format in PARSERS
        else DocumentMetadata(source_format=source_format)
    )
    source_title = None if source_format == SourceFormat.PLAIN else metadata.title
    title = readable(source_title) or readable(name) or readable(source.stem.replace("-", " "))
    work = {
        "id": str(uuid.uuid4()),
        "title": title,
        "language": metadata.language or "en",
        "kind": "book",
        "edition": metadata.extra.get("edition", "Source edition"),
        "authors": metadata.creators,
    }
    policy = {"work": work, "retainSupplementary": True}
    assets: dict[str, bytes] = {}
    evidence: dict = {"format": source_format.value, "warnings": []}
    if source_format == SourceFormat.PLAIN:
        text = source.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        model = {
            "work": work,
            "body": [node("p", p) for p in re.split(r"\n[ \t]*\n", text) if p.strip()],
        }
        evidence["normalization"] = "CRLF/CR to LF; blank lines separate paragraphs"
        placeholders = re.findall(r"\[(?:TABLE NOT SHOWN|ILLEGIBLE|UNREADABLE)[^\]]*\]", text, re.I)
        if placeholders:
            evidence["warnings"].append(
                f"Source contains {len(placeholders)} unavailable-content placeholders; their missing content requires review"
            )
        if re.search(r"(?m)^\s*\{\d+\}\s*$", text):
            evidence["warnings"].append(
                "Possible printed page labels are retained in source text; their logical placement requires review"
            )
    elif source_format == SourceFormat.PDF:
        pdf = PdfReader(source)
        if pdf.is_encrypted:
            raise ValueError("Encrypted PDF requires an accessible source before TEI conversion")
        pieces = []
        for page in pdf.pages:
            extracted = page.extract_text() or ""
            if not extracted.strip():
                raise ValueError(
                    "PDF has unreadable pages; reviewed OCR is required before TEI conversion"
                )
            pieces.append(extracted)
        text = " ".join(pieces)
        for page_no, page in enumerate(pdf.pages, 1):
            for image_no, image in enumerate(page.images, 1):
                assets[f"assets/pdf/page-{page_no}-image-{image_no}{Path(image.name).suffix}"] = (
                    image.data
                )
        for attachment_no, (filename, contents) in enumerate(pdf.attachments.items(), 1):
            suffix = Path(filename).suffix
            suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix) else ".bin"
            for occurrence, data in enumerate(contents, 1):
                assets[f"assets/pdf/attachment-{attachment_no}-{occurrence}{suffix}"] = data
        # No paragraph boundaries inferred from physical page boundaries.
        model = {"work": work, "body": [node("p", re.sub(r"[\r\n]+", " ", text))]}
        evidence["warnings"] = [
            "PDF text layer, reading order, notes and tables require visual verification; no logical headings inferred"
        ]
        evidence["normalization"] = (
            "Unstructured extracted text in one provisional paragraph; logical paragraphs, notes and tables need review"
        )
    elif source_format == SourceFormat.EPUB:
        members = archive_bytes(source)
        _heading_policy(
            policy, [xml(data) for path, data in members.items() if path.lower().endswith(".xhtml")]
        )
        # No inference of chapters from physical XHTML boundaries.
        model, assets, evidence = epub_source(source, policy)
        container = xml(members["META-INF/container.xml"])
        opf_path = container.find(".//{*}rootfile").get("full-path")
        opf = xml(members[opf_path])
        for item in opf.findall("{*}manifest/{*}item"):
            if item.get("media-type") not in {"application/xhtml+xml", "application/x-dtbncx+xml"}:
                path = local_path(opf_path, item.get("href"))
                if path not in members:
                    raise ValueError("Declared EPUB asset is missing")
                assets.setdefault("assets/source-resources/" + path, members[path])
        text = " ".join(_model_text(n) for n in model["body"])
    elif source_format in {SourceFormat.HTML, SourceFormat.XML}:
        data = source.read_bytes()
        if source_format == SourceFormat.XML:
            original = xml(data)
            if etree.QName(original).localname == "TEI":
                model, text = _tei_model(original, work, evidence)
                return _finish(model, assets, evidence, metadata, text)
        root = original if source_format == SourceFormat.XML else html_root(data)
        if source_format == SourceFormat.XML and tag(root) in {"p", "section", "div"}:
            wrapper = etree.Element("source")
            wrapper.append(root)
            root = wrapper
        _heading_policy(policy, [root])
        members = {source.name: data}
        mapper = HtmlMapper(members, policy)
        blocks = mapper.blocks(root, source.name)
        source_heads = [
            e
            for e in root.iter()
            if isinstance(e.tag, str) and (re.fullmatch(r"h[1-6]", tag(e)) or tag(e) == "title")
        ]
        mapped_heads = []

        def heads(n, inside_figure=False):
            inside_figure = inside_figure or n["tag"] == "figure"
            if n["tag"] == "head" and not inside_figure:
                mapped_heads.append(n)
            for c in n["children"]:
                heads(c, inside_figure)

        for n in blocks:
            heads(n)
        if len(source_heads) != len(mapped_heads):
            raise ValueError("HTML source heading coverage mismatch")
        for e, n in zip(source_heads, mapped_heads, strict=True):
            n["headingLevel"] = int(tag(e)[1]) if tag(e).startswith("h") else 0
        model = {"work": work, **structured_blocks(blocks, policy)}
        conform_divisions(model)
        mapper.resolve()
        assets = mapper.assets
        text = raw_reading(root, policy)
        evidence = {
            "format": source_format.value,
            "sourceText": normalized(text),
            "warnings": dict(mapper.warnings),
            "excluded": mapper.excluded,
            **source_coverage([(source.name, root)], members, policy),
        }
    elif source_format == SourceFormat.TEI:
        model, text = _tei_model(xml(source.read_bytes()), work, evidence)
    else:
        raise ValueError(
            "CTEI accepts EPUB, HTML, XML/TEI, readable PDF and UTF-8 plain text; dataset ZIP inputs require source documents"
        )
    return _finish(model, assets, evidence, metadata, text)


def _heading_policy(policy, roots):
    headings = [
        e
        for root in roots
        for e in root.iter()
        if isinstance(e.tag, str) and re.fullmatch(r"h[1-6]", tag(e))
    ]
    if headings:
        level = min(int(tag(e)[1]) for e in headings)
        top = [e for e in headings if int(tag(e)[1]) == level]
        chapters = all(re.match(r"chapter\b", "".join(e.itertext()).strip(), re.I) for e in top)
        policy.update(
            topHeadingLevel=level,
            topType="chapter" if chapters else "section",
            flattenLayoutDivs=True,
        )


def _model_text(n):
    return (n.get("text") or "") + "".join(
        _model_text(c) + (c.get("tail") or "") for c in n.get("children", [])
    )


def _tei_model(root, work, evidence):
    if root.tag != f"{{{NS}}}TEI":
        raise ValueError("Expected a standalone TEI P5 document")
    work["language"] = root.get(f"{{{XML}}}lang") or work["language"]
    text = root.find(f"{{{NS}}}text")
    if text is None:
        raise ValueError("TEI source has no reading text")
    if (
        root.find(f"{{{NS}}}standOff") is not None
        or root.find(f"{{{NS}}}teiHeader//{{{NS}}}refsDecl") is not None
    ):
        raise ValueError(
            "TEI stand-off annotations and canonical schemes require an explicit supported mapping before conversion"
        )
    if text.xpath(".//t:div[@type='surah']", namespaces={"t": NS}):
        raise ValueError(
            "Canonical surah structure requires a declared reading, numbering and segmentation scheme before conversion"
        )
    edition = root.find(f"{{{NS}}}teiHeader//{{{NS}}}edition")
    if edition is not None and "".join(edition.itertext()).strip():
        work["edition"] = "".join(edition.itertext()).strip()
    if text.get("type") in {"article", "paper"}:
        work["kind"] = "paper"
    supported = {
        "div",
        "head",
        "p",
        "lg",
        "l",
        "list",
        "item",
        "label",
        "table",
        "row",
        "cell",
        "note",
        "ref",
        "anchor",
        "hi",
        "emph",
        "quote",
        "foreign",
        "choice",
        "abbr",
        "expan",
        "gap",
        "unclear",
        "figure",
        "figDesc",
    }
    allowed_attrs = {
        "n",
        "type",
        "rend",
        "target",
        "role",
        "rows",
        "cols",
        "reason",
        f"{{{XML}}}lang",
    }

    def map_node(e):
        local = etree.QName(e).localname
        if local not in supported:
            raise ValueError(
                f"TEI source element {local} needs a supported semantic mapping before conversion"
            )
        if set(e.attrib) & {"corresp", "cRef", "from", "to", "spanTo", "ana"}:
            raise ValueError(
                "TEI source links/annotations require an explicit supported mapping before conversion"
            )
        dropped = set(e.attrib) - allowed_attrs - {f"{{{XML}}}id", "style", "facs", "rendition"}
        if dropped:
            evidence.setdefault("warnings", []).append(
                f"Source {local} attributes retained in original source asset require mapping review: {', '.join(sorted(dropped))}"
            )
        attrs = {k: v for k, v in e.attrib.items() if k in allowed_attrs}
        if local == "div" and attrs.get("type") not in DIV_TYPES:
            if attrs.get("type"):
                evidence.setdefault("warnings", []).append(
                    f"Source division type {attrs['type']!r} is retained in the original source and mapped to section; semantic mapping requires review"
                )
            attrs["type"] = "section"
        if local == "list" and attrs.get("type") not in {"ordered", "unordered"}:
            source_type = attrs.get("type") or "undeclared"
            evidence.setdefault("warnings", []).append(
                f"Source list type {source_type!r} is retained in the original source and mapped to unordered; ordering requires review"
            )
            attrs["type"] = "unordered"
        if local == "ref":
            attrs["type"] = "unresolved"
        n = node(local, e.text, **attrs)
        if e.get(f"{{{XML}}}id"):
            n["id"] = e.get(f"{{{XML}}}id")
        n["tail"] = e.tail
        n["children"] = [map_node(c) for c in e if isinstance(c.tag, str)]
        return n

    model = {"work": work}
    for region in ("front", "body", "back"):
        container = text.find(f"{{{NS}}}{region}")
        model[region] = (
            [map_node(c) for c in container if isinstance(c.tag, str)]
            if container is not None
            else []
        )
    return model, "".join(text.itertext())


def _finish(model, assets, evidence, metadata, text):
    if not model.get("body"):
        raise ValueError("Source has no readable body content")
    declared = metadata.language
    if declared is None and model["work"]["language"] != "en":
        declared = model["work"]["language"]
    if not declared:
        warnings = evidence.setdefault("warnings", [])
        message = (
            "Source language is undeclared; manifest defaults to English and requires confirmation"
        )
        if isinstance(warnings, dict):
            warnings[message] = 1
        else:
            warnings.append(message)
    language, code, ident = language_metadata(declared, text)
    model["work"]["language"] = ident
    metadata.language = ident
    metadata.extra.update(languageName=language, languageCode=code)
    return model, assets, evidence, metadata
