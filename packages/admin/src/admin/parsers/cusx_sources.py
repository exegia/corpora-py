"""Explicit source structures for C-USX; legacy graph parsers keep their contract."""

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree

from . import PARSERS
from .epub_structure import (
    MAX_BYTES,
    EpubStructure,
    _ranges,
    element_unit,
    local,
    safe_path,
    target,
    unit_text,
    walk,
    xml,
)
from .schema import DocumentMetadata, SourceFormat, Unit

TEI = "http://www.tei-c.org/ns/1.0"


@dataclass
class SourceSection:
    source_path: str
    unit: Unit
    label: str
    role: str = "document"
    linear: bool = True
    in_spine: bool = True
    start: int | None = None
    end: int | None = None
    fragment: str = ""
    head: Unit | None = None
    html_attrs: dict = field(default_factory=dict)
    namespaces: dict = field(default_factory=dict)
    source_details: dict = field(default_factory=dict)


def link_attributes(node: Unit) -> list[str]:
    keys = [key for key in ("src", "href", "xlink:href", "poster", "data") if key in node.attrs]
    keys += [
        key
        for key in node.attrs
        if ":" in key
        and key.split(":")[-1] == "href"
        and node.namespaces.get(key.split(":")[0]) == "http://www.w3.org/1999/xlink"
        and key not in keys
    ]
    if node.type in ("ref", "ptr") and "target" in node.attrs:
        keys.append("target")
    if node.type == "graphic" and "url" in node.attrs:
        keys.append("url")
    return keys


def _resources(source: Path, sections, diagnostics: list[str]) -> dict[str, bytes]:
    assets = {}
    base = source.parent.resolve()
    for section in sections:
        for node in walk(section.unit):
            for key in link_attributes(node):
                href = node.attrs[key]
                if key == "target" and len(href.split()) > 1:
                    diagnostics.append(
                        "Multiple TEI target URIs retained verbatim; relocation unavailable"
                    )
                    continue
                resolved = target(source.name, href)
                if resolved is None or resolved[0] == source.name:
                    continue
                path = base / resolved[0]
                if not path.resolve().is_relative_to(base):
                    raise ValueError("Source resource escapes the supplied source directory")
                if path.is_file():
                    assets["assets/" + safe_path(resolved[0])] = path.read_bytes()
                else:
                    diagnostics.append(f"Source resource not supplied: {resolved[0]}")
                if sum(map(len, assets.values())) > MAX_BYTES:
                    raise ValueError("Source resources exceed the supported size limit")
    return assets


def _xml_source(source: Path, fmt: SourceFormat) -> EpubStructure:
    try:
        root = xml(source.read_bytes())
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Malformed XML source: {exc}") from exc
    root_unit = element_unit(root)
    if any(node.attrs.get("xml:base") for node in walk(root_unit)) and any(
        not urlsplit(node.attrs[key]).scheme
        for node in walk(root_unit)
        for key in link_attributes(node)
    ):
        raise ValueError("XML xml:base with relative links requires explicit base resolution")
    is_tei = local(root) in ("TEI", "teiCorpus") and etree.QName(root).namespace in (None, TEI)
    if fmt == SourceFormat.TEI and not is_tei:
        raise ValueError("TEI input requires a TEI or teiCorpus root in the TEI namespace")
    title = root.find(".//{*}title")
    metadata = DocumentMetadata(
        source_format=fmt,
        title="".join(title.itertext()) if title is not None else local(root),
        creators=["".join(n.itertext()) for n in root.findall(".//{*}teiHeader//{*}author")]
        if is_tei
        else [],
        extra={
            "xml:vocabulary": "tei" if is_tei else "generic",
            "xml:stream": "Parsed element text and tails, without synthetic separators",
        },
    )
    if is_tei:
        header = root.find("{*}teiHeader")
        if header is not None:
            metadata.extra["tei:header"] = etree.tostring(header, encoding="unicode")
            for attr, tag in (
                ("publisher", "publisher"),
                ("date", "date"),
                ("identifier", "idno"),
                ("rights", "availability"),
            ):
                node = header.find(".//{*}" + tag)
                if node is not None:
                    setattr(metadata, attr, "".join(node.itertext()))
            language = header.find(".//{*}language")
            if language is not None:
                metadata.language = language.get("ident")
    _, ids, end = _ranges(root_unit, [])
    starts = {}
    # Only explicit direct TEI divisions establish documents. Nested divisions
    # remain nested, and generic XML is always one complete element tree.
    candidates = []
    if is_tei and local(root) == "teiCorpus":
        candidates = [n for n in root if local(n) == "TEI"]
    elif is_tei:
        text = root.find("{*}text")
        body = text.find("{*}body") if text is not None else None
        if body is not None:
            candidates = [n for n in body if local(n) in ("div", "div1")]
        if len(candidates) > 1 and text is not None:
            candidates += [n for n in text if local(n) in ("front", "back")]
    source_units = {}

    def pair(element, unit):
        source_units[element] = unit
        index = int(element.text is not None)
        for child in element:
            pair(child, unit.children[index])
            index += 1 + int(child.tail is not None)

    pair(root, root_unit)
    # Index Unit identity rather than requiring the source to have xml:id.
    event_index = {id(u): i for i, u in enumerate(walk(root_unit))}
    if len(candidates) > 1:
        for element in candidates:
            unit = source_units[element]
            start = event_index[id(unit)]
            head = element.find("{*}head")
            label = (
                "".join(head.itertext())
                if head is not None
                else element.get("n") or element.get("type") or local(element)
            )
            starts[start] = {
                "label": label,
                "role": element.get("type") or local(element),
                "fragment": element.get("{http://www.w3.org/XML/1998/namespace}id")
                or element.get("id", ""),
            }
    if starts:
        first = min(starts)
        prefix = list(walk(root_unit))[:first]
        if all(u.type in ("TEI", "teiCorpus", "text", "body") and not u.tokens for u in prefix):
            starts[0] = starts.pop(first)
    bounds = sorted({0, end, *starts})
    parts, _, _ = _ranges(root_unit, bounds)
    sections = []
    for index, part in enumerate(parts):
        info = starts.get(bounds[index], {})
        sections.append(
            SourceSection(
                source.name,
                part,
                info.get("label") or metadata.title or source.stem,
                role=info.get("role") or ("front_matter" if starts else "document"),
                start=bounds[index],
                end=bounds[index + 1],
                fragment=info.get("fragment", ""),
            )
        )
    if "".join(unit_text(s.unit) for s in sections) != "".join(root.itertext()):
        raise ValueError("XML division projection changed source text")
    diagnostics = [
        "Original XML bytes retained, including comments/declarations; stream uses parsed XML text"
    ]
    assets = _resources(source, sections, diagnostics)
    return EpubStructure(sections, {}, assets, diagnostics, metadata)


def _pdf_source(source: Path) -> EpubStructure:
    from pypdf import PdfReader

    from .pdf_ocr import encoded, extract_pdf

    extraction = extract_pdf(source)
    reader = PdfReader(source, strict=True)
    assets = {
        "assets/pdf/ocr/snapshot.json": encoded(extraction.snapshot),
        "assets/pdf/ocr/provenance.json": encoded(extraction.provenance),
    }
    diagnostics = [
        "PDF extracted using pinned Docling forced full-page OCR; source fidelity requires independent validation",
        "PDF documents are explicit pages; bookmarks are navigation, not inferred chapter boundaries",
        "OCR block provenance retained; native selection mappings are not established",
    ]
    sections = []
    for index, unit in enumerate(extraction.document.units, start=1):
        for number, image in enumerate(reader.pages[index - 1].images, start=1):
            path = f"assets/pdf/page-{index:04d}/image-{number:04d}{Path(image.name).suffix}"
            assets[path] = image.data
            unit.children.append(Unit(type="image", attrs={"src": path, "name": image.name, "evidence": "native-pdf-image"}))
        sections.append(SourceSection(
            source.name, unit, f"Page {reader.page_labels[index - 1]}", role="page",
            fragment=unit.attrs["id"], source_details={
                "page_number": index, "page_label": reader.page_labels[index - 1],
            },
        ))

    def outlines(items):
        entries = []
        for item in items:
            if isinstance(item, list):
                if not entries:
                    raise ValueError("PDF outline hierarchy has no parent destination")
                entries[-1]["children"].extend(outlines(item))
                continue
            number = reader.get_destination_page_number(item)
            entry = {"label": str(item.title), "source_href": "", "role": "bookmark", "children": []}
            if number is not None and 0 <= number < len(sections):
                fragment = f"pdf-page-{number + 1}"
                entry.update(source_path=source.name, fragment=fragment, source_href="#" + fragment)
            else:
                diagnostics.append("Unresolved PDF bookmark retained: " + str(item.title))
            entries.append(entry)
        return entries

    return EpubStructure(sections, {"bookmarks": outlines(reader.outline)}, assets,
                         diagnostics, extraction.document.metadata)


def read_cusx_source(source: Path, fmt: SourceFormat) -> EpubStructure:
    if fmt in (SourceFormat.XML, SourceFormat.TEI):
        return _xml_source(source, fmt)
    if fmt == SourceFormat.PDF:
        return _pdf_source(source)
    document = PARSERS[fmt].parse(str(source))
    unit = Unit(type="document", children=document.units)
    diagnostics = []
    if fmt == SourceFormat.MARKDOWN:
        diagnostics.append(
            "Markdown snapshot is verbatim source syntax; decoded semantic nodes carry content attributes without duplicating stream text"
        )
    sections = [SourceSection(source.name, unit, document.metadata.title or source.stem)]
    assets = _resources(source, sections, diagnostics)
    return EpubStructure(sections, {}, assets, diagnostics, document.metadata)
