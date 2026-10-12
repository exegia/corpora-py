"""EPUB CFI DOM ranges with UTF-16 offsets and exact, pinned quote verification.

Supports element steps with optional ID assertions and character offsets. Text
assertions, side bias, temporal/spatial offsets and cross-resource ranges reject.
"""

import io
import posixpath
import re
import zipfile
from pathlib import PurePosixPath

from corpora_linking import Endpoint, EpubLocator, TextLocator, verify_text_anchor

from .linking_html import utf16_to_scalar
from .linking_pdf import sha256_revision


def _xml(data):
    from lxml import etree

    root = etree.fromstring(
        data,
        parser=etree.XMLParser(
            resolve_entities=False, no_network=True, load_dtd=False, recover=False
        ),
    )
    if root.getroottree().docinfo.doctype:
        raise ValueError("CFI DOM requires XML without DOCTYPE")
    return root


def _read(archive, path):
    if (
        not path
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or "\\" in path
    ):
        raise ValueError("unsafe EPUB resource path")
    if archive.namelist().count(path) != 1:
        raise ValueError("missing or ambiguous EPUB resource")
    return archive.read(path)


def _resource(data: bytes, package_path: str, href: str):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        container = _xml(_read(archive, "META-INF/container.xml"))
        roots = container.xpath("//*[local-name()='rootfile']/@full-path")
        if len(roots) != 1 or roots[0] != package_path:
            raise ValueError("ambiguous or stale EPUB package")
        package = _xml(_read(archive, package_path))
        root = _xml(_read(archive, posixpath.join(posixpath.dirname(package_path), href)))
        return package, root


def _package_path(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        roots = _xml(_read(archive, "META-INF/container.xml")).xpath(
            "//*[local-name()='rootfile']/@full-path"
        )
        if len(roots) != 1:
            raise ValueError("EPUB CFI requires one package rootfile")
        return roots[0]


def _elements(node):
    return [child for child in node if isinstance(child.tag, str)]


def _walk(root, path):
    current = root
    for step, assertion in path:
        if step % 2 or step < 2:
            raise ValueError("CFI element path requires positive even steps")
        children = _elements(current)
        index = step // 2 - 1
        if index >= len(children):
            raise ValueError("stale CFI element step")
        current = children[index]
        if assertion is not None and current.get("id") != assertion:
            raise ValueError("stale CFI ID assertion")
    return current


def _parse_steps(value):
    tokens = re.findall(r"/([1-9][0-9]*)(?:\[([A-Za-z0-9_.:-]+)\])?", value)
    reconstructed = "".join(
        "/" + step + ("[" + identifier + "]" if identifier else "") for step, identifier in tokens
    )
    if reconstructed != value or not tokens:
        raise ValueError("unsupported CFI steps/assertions")
    return [(int(step), identifier or None) for step, identifier in tokens]


def _dom(root):
    # XML comments do not change CFI element numbering. Adjacent text separated
    # only by comments is one CFI character-data slot.
    nodes = []
    offset = 0

    def visit(node, path):
        nonlocal offset
        slots = [node.text or ""]
        elements = _elements(node)
        for child in node:
            if isinstance(child.tag, str):
                slots.append(child.tail or "")
            else:
                slots[-1] += child.tail or ""
        for index, slot in enumerate(slots):
            if slot:
                nodes.append(((*path, 2 * index + 1), offset, slot))
                offset += len(slot)
            if index < len(elements):
                visit(elements[index], (*path, 2 * (index + 1)))

    visit(root, ())
    return "".join(quote for path, start, quote in nodes), nodes


def _point(root, nodes, steps, utf16):
    if not steps or steps[-1][0] % 2 == 0 or steps[-1][1] is not None:
        raise ValueError("CFI range must end in a character-data step")
    _walk(root, steps[:-1])
    path = tuple(step for step, assertion in steps)
    matches = [(start, quote) for candidate, start, quote in nodes if candidate == path]
    if len(matches) != 1:
        raise ValueError("CFI text slot unavailable")
    start, quote = matches[0]
    return start + utf16_to_scalar(quote, utf16)


def _spine(package, package_steps, href):
    itemref = _walk(package, package_steps)
    if (
        itemref.tag.rsplit("}", 1)[-1] != "itemref"
        or itemref.getparent().tag.rsplit("}", 1)[-1] != "spine"
    ):
        raise ValueError("CFI package component must select a spine itemref")
    manifest = package.xpath("//*[local-name()='manifest']/*[@id=$id]", id=itemref.get("idref"))
    if (
        len(manifest) != 1
        or manifest[0].get("href") != href
        or manifest[0].get("media-type") != "application/xhtml+xml"
    ):
        raise ValueError("CFI spine/href mismatch")


def retrieve_epub_cfi_selection(data: bytes, endpoint: Endpoint) -> str:
    if (
        endpoint.revision != sha256_revision(data)
        or len(endpoint.locators) != 1
        or not isinstance(endpoint.locators[0], EpubLocator)
    ):
        raise ValueError("EPUB CFI requires a pinned asset")
    locator = endpoint.locators[0]
    if (
        not locator.cfi.startswith("epubcfi(")
        or not locator.cfi.endswith(")")
        or locator.cfi.count("!") != 1
    ):
        raise ValueError("unsupported EPUB CFI")
    package_part, content = locator.cfi[8:-1].split("!")
    parts = content.split(",")
    if len(parts) != 3:
        raise ValueError("EPUB exact selection requires a CFI range")
    package, root = _resource(data, _package_path(data), locator.href)
    _spine(package, _parse_steps(package_part), locator.href)
    base = _parse_steps(parts[0]) if parts[0] else []
    text, nodes = _dom(root)
    bounds = []
    for point in parts[1:]:
        match = re.fullmatch(r"(.+):([0-9]+)", point)
        if match is None:
            raise ValueError("unsupported CFI range offset/assertion")
        bounds.append(_point(root, nodes, base + _parse_steps(match[1]), int(match[2])))
    selector = locator.text
    if (
        selector is None
        or selector.stream_id != "epub-cfi-dom"
        or selector.normalization != "preserve"
        or (selector.start, selector.end) != tuple(bounds)
    ):
        raise ValueError("CFI range requires matching DOM scalar text evidence")
    if (
        verify_text_anchor(
            selector,
            text,
            expected_revision=endpoint.revision or "",
            actual_revision=sha256_revision(data),
        )
        != "valid"
    ):
        raise ValueError("stale EPUB CFI quote/context")
    return text[selector.start : selector.end]


def make_epub_cfi_selection(
    data: bytes, base: Endpoint, *, asset_id: str, href: str, start: int, end: int
) -> Endpoint:
    package, root = _resource(data, _package_path(data), href)
    manifest = package.xpath("//*[local-name()='manifest']/*[@href=$href]", href=href)
    if len(manifest) != 1:
        raise ValueError("ambiguous EPUB href")
    spine = package.xpath("//*[local-name()='spine']/*[@idref=$id]", id=manifest[0].get("id"))
    if len(spine) != 1:
        raise ValueError("ambiguous EPUB spine item")

    def element_path(node):
        steps = []
        while node is not package:
            parent = node.getparent()
            if parent is None:
                raise ValueError("EPUB package path unavailable")
            steps.append(2 * (_elements(parent).index(node) + 1))
            node = parent
        return "/".join(str(step) for step in reversed(steps))

    text, nodes = _dom(root)
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError("EPUB range must be nonempty DOM scalar bounds")

    def point(offset, ending=False):
        candidates = [
            (path, begin, quote)
            for path, begin, quote in nodes
            if begin <= offset < begin + len(quote)
            or (ending and begin < offset == begin + len(quote))
        ]
        if not candidates:
            raise ValueError("EPUB character boundary unavailable")
        path, begin, quote = candidates[0]
        units = len(quote[: offset - begin].encode("utf-16-le")) // 2
        return "".join("/" + str(step) for step in path) + ":" + str(units)

    cfi = "epubcfi(/" + element_path(spine[0]) + "!," + point(start) + "," + point(end, True) + ")"
    selector = TextLocator(
        stream_id="epub-cfi-dom",
        start=start,
        end=end,
        exact=text[start:end],
        prefix=text[max(0, start - 32) : start],
        suffix=text[end : end + 32],
    )
    endpoint = Endpoint.model_validate(
        {
            **base.model_dump(),
            "locators": [EpubLocator(asset_id=asset_id, href=href, cfi=cfi, text=selector)],
        }
    )
    retrieve_epub_cfi_selection(data, endpoint)
    return endpoint
