"""EPUB navigation and lossless body ranges, without inferred segmentation."""

import copy
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from lxml import etree

from .schema import DocumentMetadata, SourceFormat, Unit, tokenize

EPUB = "http://www.idpf.org/2007/ops"
MAX_BYTES = 256 * 1024 * 1024


def safe_path(path: str) -> str:
    if (
        not path
        or "\\" in path
        or path.startswith("/")
        or any(part in ("", ".", "..") for part in path.split("/"))
    ):
        raise ValueError(f"Unsafe EPUB/package member: {path}")
    return path


def target(base: str, href: str) -> tuple[str, str] | None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if path.startswith("/") or "\\" in path:
        raise ValueError("Absolute EPUB resource path is unsupported")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), path)) if path else base
    return safe_path(resolved), unquote(parsed.fragment)


def xml(data: bytes) -> etree._Element:
    # Never resolve external/internal entities or silently repair malformed XHTML.
    if b"<!ENTITY" in data.upper():
        raise ValueError("EPUB entity declarations are unsupported")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=True, remove_pis=True
    )
    root = etree.fromstring(data, parser)
    if any(isinstance(node, etree._Entity) for node in root.iter()):
        raise ValueError("Unresolved EPUB entity")
    return root


def local(node: etree._Element) -> str:
    return etree.QName(node).localname


def attributes(node: etree._Element) -> dict[str, str]:
    result = {}
    for name, value in node.attrib.items():
        q = etree.QName(name)
        if q.namespace:
            prefix = (
                "xml"
                if q.namespace == "http://www.w3.org/XML/1998/namespace"
                else next((p for p, ns in node.nsmap.items() if p and ns == q.namespace), None)
            )
            if prefix is None:
                raise ValueError("Namespaced attribute requires a source prefix")
            name = f"{prefix}:{q.localname}"
        result[name] = value
    return result


def element_unit(node: etree._Element) -> Unit:
    """Preserve namespaces, attributes and every text/tail run, including spaces."""
    children = []
    if node.text is not None:
        children.append(Unit(type="text", tokens=tokenize(node.text)))
    for child in node:
        if isinstance(child.tag, str):
            children.append(element_unit(child))
        if child.tail is not None:
            children.append(Unit(type="text", tokens=tokenize(child.tail)))
    return Unit(
        type=local(node),
        namespace=etree.QName(node).namespace,
        namespaces={prefix or "": uri for prefix, uri in node.nsmap.items()},
        attrs=attributes(node),
        children=children,
    )


def unit_text(unit: Unit) -> str:
    return "".join(t.text + t.after for t in unit.tokens) + "".join(
        unit_text(child) for child in unit.children
    )


def walk(unit: Unit):
    yield unit
    for child in unit.children:
        yield from walk(child)


@dataclass
class EpubSection:
    source_path: str
    unit: Unit
    label: str
    role: str
    linear: bool
    in_spine: bool
    start: int
    end: int
    fragment: str = ""
    head: Unit | None = None
    html_attrs: dict[str, str] = field(default_factory=dict)
    namespaces: dict[str, str] = field(default_factory=dict)


@dataclass
class EpubStructure:
    sections: list[EpubSection]
    navigation: dict[str, list[dict]]
    assets: dict[str, bytes]
    diagnostics: list[str]
    metadata: DocumentMetadata


def _nav_list(container: etree._Element, base: str) -> list[dict]:
    result = []
    for li in container:
        if not isinstance(li.tag, str) or local(li) != "li":
            continue
        labels = [n for n in li if isinstance(n.tag, str) and local(n) in ("a", "span")]
        if len(labels) != 1:
            raise ValueError("Ambiguous EPUB navigation entry")
        label = labels[0]
        entry = {"label": "".join(label.itertext()), "source_href": label.get("href", "")}
        if label.get("href"):
            resolved = target(base, label.get("href"))
            if resolved is None:
                entry["external_href"] = label.get("href")
            else:
                entry["source_path"], entry["fragment"] = resolved
        entry["role"] = label.get(f"{{{EPUB}}}type", "")
        entry["children"] = []
        for child in li:
            if isinstance(child.tag, str) and local(child) == "ol":
                entry["children"].extend(_nav_list(child, base))
        result.append(entry)
    return result


def _ncx_nodes(container: etree._Element, base: str) -> list[dict]:
    entries = []
    for node in container:
        if not isinstance(node.tag, str) or local(node) not in ("navPoint", "pageTarget"):
            continue
        labels = node.findall("{*}navLabel/{*}text")
        contents = node.findall("{*}content")
        if len(labels) != 1 or len(contents) != 1:
            raise ValueError("Ambiguous NCX navigation")
        href = contents[0].get("src", "")
        resolved = target(base, href)
        entry = {
            "label": "".join(labels[0].itertext()),
            "source_href": href,
            "role": "",
            "children": _ncx_nodes(node, base),
        }
        if resolved is None:
            entry["external_href"] = href
        else:
            entry["source_path"], entry["fragment"] = resolved
        entries.append(entry)
    return entries


def nav_entries(entries: list[dict]):
    for entry in entries:
        yield entry
        yield from nav_entries(entry.get("children", []))


def _ranges(body: Unit, boundaries: list[int]) -> tuple[list[Unit], dict[str, int], int]:
    # Preorder event positions distinguish adjacent empty anchors at the same
    # text offset. Cutting copies enclosing structure but assigns each text run
    # and original ID to exactly one segment.
    spans = {}
    ids = {}
    position = 0

    def index(unit):
        nonlocal position
        start = position
        position += 1
        source_id = unit.attrs.get("id") or unit.attrs.get("xml:id")
        if source_id:
            if source_id in ids:
                raise ValueError(f"Duplicate source ID: {source_id}")
            ids[source_id] = start
        for child in unit.children:
            index(child)
        spans[id(unit)] = start, position

    index(body)

    def cut(unit, low, high):
        start, end = spans[id(unit)]
        if end <= low or start >= high:
            return None
        if low <= start and end <= high:
            return copy.deepcopy(unit)
        result = unit.model_copy(deep=True)
        result.children = [c for child in unit.children if (c := cut(child, low, high)) is not None]
        if start < low:
            result.tokens = []
            for key in ("id", "xml:id"):
                if key in result.attrs:
                    result.source_attrs[key] = result.attrs.pop(key)
        return result

    return (
        [cut(body, a, b) for a, b in zip(boundaries, boundaries[1:], strict=False)],
        ids,
        position,
    )


def read_epub_structure(source: str) -> EpubStructure:
    diagnostics = []
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos if not i.is_dir()]
        if len(names) != len(set(names)) or sum(i.file_size for i in infos) > MAX_BYTES:
            raise ValueError("Duplicate or oversized EPUB members")
        for name in names:
            safe_path(name)
        data = {name: archive.read(name) for name in names}
    container = xml(data["META-INF/container.xml"])
    roots = container.findall("{*}rootfiles/{*}rootfile")
    if len(roots) != 1:
        raise ValueError("EPUB requires one explicit package root")
    opf_path = safe_path(roots[0].get("full-path", ""))
    opf = xml(data[opf_path])
    metadata_node = opf.find("{*}metadata")
    if metadata_node is None:
        raise ValueError("EPUB package metadata is missing")
    dc = {}
    for child in metadata_node:
        if etree.QName(child).namespace == "http://purl.org/dc/elements/1.1/":
            dc.setdefault(local(child), []).append("".join(child.itertext()))
    metadata = DocumentMetadata(
        source_format=SourceFormat.EPUB,
        creators=dc.get("creator", []),
        subjects=dc.get("subject", []),
        **{
            field: dc.get(source_field, [None])[0]
            for field, source_field in {
                "title": "title",
                "language": "language",
                "publisher": "publisher",
                "date": "date",
                "description": "description",
                "identifier": "identifier",
                "rights": "rights",
            }.items()
        },
        extra={"epub:package-metadata": etree.tostring(metadata_node, encoding="unicode")},
    )
    items = {}
    for item in opf.findall("{*}manifest/{*}item"):
        item_id = item.get("id")
        if not item_id or item_id in items:
            raise ValueError("Missing or duplicate EPUB manifest ID")
        resolved = target(opf_path, item.get("href", ""))
        if resolved is None or resolved[1]:
            raise ValueError("Remote/fragment EPUB manifest resource is unsupported")
        path = resolved[0]
        if path not in data:
            raise ValueError(f"Missing EPUB resource: {path}")
        items[item_id] = {**dict(item.attrib), "path": path}
    html_items = [
        v for v in items.values() if v.get("media-type") in ("application/xhtml+xml", "text/html")
    ]
    html_paths = {v["path"] for v in html_items}
    if not html_paths:
        raise ValueError("EPUB contains no XHTML documents")
    spine = []
    for itemref in opf.findall("{*}spine/{*}itemref"):
        item = items.get(itemref.get("idref"))
        if not item or item["path"] not in html_paths:
            raise ValueError("Unsupported or missing EPUB spine document")
        if any(p == item["path"] for p, _ in spine):
            raise ValueError("Repeated EPUB spine resource requires explicit occurrence mapping")
        spine.append((item["path"], itemref.get("linear", "yes") != "no"))
    if not spine:
        raise ValueError("EPUB reading order requires a spine")

    navigation = {}
    nav_items = [v for v in html_items if "nav" in v.get("properties", "").split()]
    if len(nav_items) > 1:
        raise ValueError("Multiple EPUB navigation documents are ambiguous")
    for item in nav_items:
        root = xml(data[item["path"]])
        for nav in root.iter():
            if local(nav) != "nav":
                continue
            for kind in nav.get(f"{{{EPUB}}}type", "").split():
                lists = nav.findall("{*}ol")
                if len(lists) != 1 or kind in navigation:
                    raise ValueError("Ambiguous EPUB navigation list")
                navigation[kind] = _nav_list(lists[0], item["path"])
    ncx_id = opf.find("{*}spine").get("toc")
    if ncx_id and ncx_id not in items:
        raise ValueError("EPUB spine references a missing NCX resource")
    ncx = (
        items.get(ncx_id)
        if ncx_id
        else next(
            (v for v in items.values() if v.get("media-type") == "application/x-dtbncx+xml"), None
        )
    )
    if ncx:
        ncx_root = xml(data[ncx["path"]])
        nav_map = ncx_root.find("{*}navMap")
        if nav_map is None:
            raise ValueError("NCX navigation map is missing")
        ncx_toc = _ncx_nodes(nav_map, ncx["path"])
        if "toc" not in navigation:
            navigation["toc"] = ncx_toc
        else:
            navigation["ncx-toc"] = ncx_toc
            primary_targets = {
                (e.get("source_path"), e.get("fragment", ""))
                for e in nav_entries(navigation["toc"])
            }
            ncx_targets = {
                (e.get("source_path"), e.get("fragment", "")) for e in nav_entries(ncx_toc)
            }
            primary_targets.discard((None, ""))
            ncx_targets.discard((None, ""))
            if primary_targets != ncx_targets:
                diagnostics.append(
                    "EPUB3 TOC and NCX differ; EPUB3 defines boundaries and both are retained"
                )
        page_list = ncx_root.find("{*}pageList")
        if page_list is not None:
            navigation["ncx-page-list"] = _ncx_nodes(page_list, ncx["path"])
    if "toc" not in navigation:
        diagnostics.append(
            "No EPUB TOC/NCX; unsplit spine documents retained without inferred chapters"
        )
        navigation["toc"] = []
    roles = {
        (e.get("source_path"), e.get("fragment", "")): e["role"]
        for e in nav_entries(navigation.get("landmarks", []))
    }
    for entry in nav_entries(navigation["toc"]):
        if entry.get("source_path") and entry["source_path"] not in html_paths:
            raise ValueError("EPUB TOC points to a missing/non-XHTML resource")

    ordered = [(p, linear, True) for p, linear in spine]
    ordered += [
        (v["path"], False, False) for v in html_items if v["path"] not in {p for p, _ in spine}
    ]
    if any(not in_spine for _, _, in_spine in ordered):
        diagnostics.append("Non-spine XHTML retained as supplementary documents")
    sections = []
    for path, linear, in_spine in ordered:
        root = xml(data[path])
        bodies = root.findall("{*}body")
        if len(bodies) != 1:
            raise ValueError(f"EPUB document requires one body: {path}")
        body = element_unit(bodies[0])
        # Index once to locate TOC fragments; then cut at every distinct target.
        _, ids, end = _ranges(body, [])
        entries = [e for e in nav_entries(navigation["toc"]) if e.get("source_path") == path]
        starts = {}
        for entry in entries:
            fragment = entry.get("fragment", "")
            if fragment and fragment not in ids:
                raise ValueError(f"Missing TOC anchor: {path}#{fragment}")
            start = ids[fragment] if fragment else 0
            starts.setdefault(start, entry)
        boundaries = sorted({0, end, *starts})
        parts, _, _ = _ranges(body, boundaries)
        for i, part in enumerate(parts):
            entry = starts.get(boundaries[i], {})
            # Preserve pre-TOC content rather than discarding it or claiming
            # that it is a chapter. Even whitespace prefixes remain explicit.
            label = entry.get("label") or PurePosixPath(path).stem
            fragment = entry.get("fragment", "")
            role = roles.get((path, fragment), roles.get((path, ""), "section"))
            if path in {v["path"] for v in nav_items}:
                role = "navigation"
            if entries and not entry:
                role = "preamble"
            if not entries:
                diagnostics.append(f"No TOC boundary for {path}; complete source document retained")
            sections.append(
                EpubSection(
                    source_path=path,
                    unit=part,
                    label=label,
                    role=role,
                    linear=linear,
                    in_spine=in_spine,
                    start=boundaries[i],
                    end=boundaries[i + 1],
                    fragment=fragment,
                    head=element_unit(root.find("{*}head"))
                    if root.find("{*}head") is not None
                    else None,
                    html_attrs=attributes(root),
                    namespaces={prefix or "": uri for prefix, uri in root.nsmap.items()},
                )
            )
        if "".join(unit_text(p) for p in parts) != "".join(bodies[0].itertext()):
            raise ValueError("EPUB segmentation changed source text")
    assets = {
        f"assets/{name}": value
        for name, value in data.items()
        if name not in html_paths and name not in ("mimetype", "META-INF/container.xml", opf_path)
    }
    return EpubStructure(sections, navigation, assets, list(dict.fromkeys(diagnostics)), metadata)
