"""Private TF -> chapter package exporter; conversion evidence is external.

Content is read only from accepted Text-Fabric nodes. The source artifact
supplies bibliographic metadata, stylesheet rules and non-text assets.
"""

import hashlib
import json
import mimetypes
import posixpath
import re
import unicodedata
from collections import defaultdict
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import cssselect2
import tinycss2
from lxml import etree as etree
from tf.fabric import Fabric

from .cusx.validate_package import normalize_content
from .cusx.validate_package import xml_json as encode

CX = "urn:corpora:usx-extension:0.1"
Q = "{" + CX + "}"
XML_PARSER = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)


def write_xml(path, root, pretty=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=pretty)
    )


def append(parent, value):
    if isinstance(value, str):
        if len(parent):
            parent[-1].tail = (parent[-1].tail or "") + value
        else:
            parent.text = (parent.text or "") + value
    else:
        parent.append(value)


def decode(value):
    name = "{" + value["namespace"] + "}" + value["name"] if value["namespace"] else value["name"]
    root = etree.Element(
        name, attrib=value["attributes"], nsmap={"cx": CX} if value["namespace"] == CX else None
    )
    for child in value.get("content", []):
        append(root, child if isinstance(child, str) else decode(child))
    return root


def property_element(parent, name, value, state=None):
    attrs = {"name": name}
    match = re.fullmatch(r"(-?(?:\d*\.)?\d+)(pt|px|in|cm|mm|em|rem|%)", value)
    if match:
        value, attrs["unit"] = match.groups()
    if state:
        attrs["state"] = state
    etree.SubElement(parent, "property", **attrs).text = value


def export(publication, tf_dir, package, work_id, title):
    from .cusx.validate_xml import grammar, validate

    package.mkdir(exist_ok=True)
    usx_dir = package / "release/USX_1"
    json_dir = package / "release/JSON_1"
    usx_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    features = [
        f.stem
        for f in tf_dir.glob("*.tf")
        if f.is_file() and f.stem not in {"otype", "oslots", "otext"}
    ]
    api = Fabric(locations=str(tf_dir), silent="deep").load(" ".join(features), silent="deep")
    if api is None:
        raise ValueError("Accepted Text-Fabric cannot be loaded")
    node_features, edge_features = api.F, api.E

    class MissingFeature:
        def v(self, node):
            return None

    for name in (
        "id",
        "class",
        "style",
        "href",
        "type",
        "role",
        "src",
        "alt",
        "colspan",
        "rowspan",
        "align",
    ):
        if name not in features:
            setattr(node_features, name, MissingFeature())
    by_path = {
        node_features.source_path.v(n): n
        for n in range(node_features.otype.maxSlot + 1, node_features.otype.maxNode + 1)
        if node_features.source_path.v(n) is not None
    }
    child_nodes = defaultdict(list)
    for path, node in by_path.items():
        if "/" in path:
            parent, order = path.rsplit("/", 1)
            child_nodes[parent].append((int(order), node))

    def kids(node):
        return [n for _, n in sorted(child_nodes[node_features.source_path.v(node)])]

    def text(node):
        return "".join(
            (node_features.text.v(s) or "") + (node_features.after.v(s) or "")
            for s in edge_features.oslots.s(node)
        )

    source_sections = [by_path[str(i)] for i in range(len(publication.document.units))]
    metadata_values = publication.metadata
    source_style_sheets = list(publication.stylesheets.items())
    navigation_labels = publication.labels
    asset_map = {}
    asset_mime = {}
    for path, media, data, cover in publication.assets:
        suffix = PurePosixPath(path).suffix.lower()
        role = "cover" if cover else "asset-" + hashlib.sha256(data).hexdigest()[:16]
        destination = package / "release/assets" / (role + suffix)
        if destination.exists() and destination.read_bytes() != data:
            destination = destination.with_name(
                "asset-" + hashlib.sha256(data).hexdigest()[:16] + suffix
            )
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(data)
        asset_map[path] = destination.relative_to(package).as_posix()
        asset_mime[asset_map[path]] = media

    def css_value(value, origin):
        def replace_url(match):
            href = match.group(2)
            parts = urlsplit(href)
            if parts.scheme or parts.netloc or href.startswith("#"):
                return match.group(0)
            from ._cusx_source import local_path

            resource = local_path(origin, href)
            if resource not in asset_map:
                raise ValueError("CSS selects a missing or unsupported asset")
            target = asset_map[resource].removeprefix("release/")
            if parts.fragment:
                target += "#" + parts.fragment
            return 'url("' + target + '")'

        return re.sub(r"url\(\s*(['\"]?)(.*?)\1\s*\)", replace_url, value, flags=re.I)

    # Reconstruct the evidenced element tree for CSS matching; never publish its
    # source tags, paths or source class names as conversion metadata in USX.
    source_elements = {}

    def source_tree(node):
        tag = "body" if node_features.otype.v(node) == "chapter" else node_features.tag.v(node)
        element = etree.Element(tag)
        source_elements[node] = element
        for name in features:
            if name in {"tag", "source_path", "name", "label", "uid"}:
                continue
            value = api.Fs(name).v(node) if name in features else None
            if value:
                element.set(name, value)
        for child in kids(node):
            if node_features.tag.v(child) == "text":
                append(element, text(child))
            else:
                element.append(source_tree(child))
        return element

    style_diagnostics = []
    physical_properties = {
        "position",
        "top",
        "bottom",
        "left",
        "right",
        "page",
        "break-before",
        "break-after",
        "page-break-before",
        "page-break-after",
        "page-break-inside",
        "float",
    }
    css_by_node = {}
    state_by_node = defaultdict(dict)
    inherited = {
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "font-variant",
        "color",
        "text-align",
        "line-height",
    }
    for section in source_sections:
        matcher = cssselect2.Matcher()
        state_rules = []
        for path in publication.section_css[node_features.name.v(section)]:
            css = publication.stylesheets[path]
            for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True):
                if rule.type != "qualified-rule":
                    style_diagnostics.append(
                        {"file": path, "reason": "unsupported CSS rule", "kind": rule.type}
                    )
                    continue
                declarations = [
                    d
                    for d in tinycss2.parse_declaration_list(
                        rule.content, skip_comments=True, skip_whitespace=True
                    )
                    if d.type == "declaration"
                ]
                properties = {
                    d.lower_name: (
                        css_value(tinycss2.serialize(d.value).strip(), path),
                        d.important,
                    )
                    for d in declarations
                    if d.lower_name not in physical_properties
                }
                omitted = [
                    d.lower_name for d in declarations if d.lower_name in physical_properties
                ]
                selector_text = tinycss2.serialize(rule.prelude).strip()
                if omitted:
                    style_diagnostics.append(
                        {
                            "file": path,
                            "selector": selector_text,
                            "omitted_physical_properties": omitted,
                        }
                    )
                for selector in selector_text.split(","):
                    selector = selector.strip()
                    state_match = re.search(r":(hover|visited|link|first-letter)$", selector)
                    if state_match:
                        state_rules.append(
                            (selector[: state_match.start()], state_match[1], properties)
                        )
                        continue
                    for compiled in cssselect2.compile_selector_list(selector):
                        matcher.add_selector(compiled, properties)
        tree = source_tree(section)
        wrappers = list(cssselect2.ElementWrapper.from_html_root(tree).iter_subtree())
        reverse = {id(el): n for n, el in source_elements.items()}
        for wrapper in wrappers:
            node = reverse[id(wrapper.etree_element)]
            values = {
                k: v
                for k, v in css_by_node.get(
                    reverse.get(id(wrapper.parent.etree_element)) if wrapper.parent else None, {}
                ).items()
                if k in inherited
            }
            priorities = {}
            for specificity, order, _pseudo, payload in matcher.match(wrapper):
                for name, (value, important) in payload.items():
                    priority = (important, specificity, order)
                    if priority >= priorities.get(name, (False, (-1, -1, -1), -1)):
                        values[name] = value
                        priorities[name] = priority
            for declaration in tinycss2.parse_declaration_list(
                wrapper.etree_element.get("style", ""), skip_comments=True, skip_whitespace=True
            ):
                if (
                    declaration.type == "declaration"
                    and declaration.lower_name not in physical_properties
                ):
                    name = declaration.lower_name
                    priority = (declaration.important, (1_000_000, 0, 0), 0)
                    if priority >= priorities.get(name, (False, (-1, -1, -1), -1)):
                        values[name] = css_value(
                            tinycss2.serialize(declaration.value).strip(),
                            node_features.name.v(section),
                        )
            css_by_node[node] = values
            for selector, state, properties in state_rules:
                try:
                    matches = any(
                        c.test(wrapper) for c in cssselect2.compile_selector_list(selector)
                    )
                except cssselect2.SelectorError:
                    matches = False
                if matches:
                    state_by_node[node].setdefault(state, {}).update(
                        {k: v for k, (v, _) in properties.items()}
                    )

    def descendants(node):
        yield node
        for child in kids(node):
            yield from descendants(child)

    def slug(value):
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:96]

    def roman(number):
        result = ""
        for value, symbol in [
            (1000, "m"),
            (900, "cm"),
            (500, "d"),
            (400, "cd"),
            (100, "c"),
            (90, "xc"),
            (50, "l"),
            (40, "xl"),
            (10, "x"),
            (9, "ix"),
            (5, "v"),
            (4, "iv"),
            (1, "i"),
        ]:
            while number >= value:
                result += symbol
                number -= value
        return result

    sections, file_map, used_keys = [], {}, set()
    for position, node in enumerate(source_sections):
        headings = [
            (n, text(n).strip())
            for n in descendants(node)
            if re.fullmatch(r"h[1-6]", node_features.tag.v(n) or "") and text(n).strip()
        ]
        chapter = next(
            (
                (n, re.match(r"^Chapter\s+(\d+|[IVXLCDM]+)(?:[.\s]|$)", h, re.I))
                for n, h in headings
                if re.match(r"^Chapter\s+(\d+|[IVXLCDM]+)(?:[.\s]|$)", h, re.I)
            ),
            None,
        )
        label = navigation_labels.get(node_features.name.v(node)) or (
            headings[0][1] if headings else f"Section {position + 1}"
        )
        # Labels and chapter numbering describe content, never XHTML container names.
        number = chapter[1].group(1) if chapter else None
        key = (
            "chapter-"
            + (
                roman(int(number))
                if number.isdecimal() and 0 < int(number) < 4000
                else slug(number)
            )
            if number
            else slug(label) or f"section-{position + 1}"
        )
        if key in used_keys:
            key += "-" + str(position + 1)
        used_keys.add(key)
        role = (
            "chapter"
            if chapter
            else (
                "frontMatter"
                if re.search(r"about|title page|copyright|preface|dedication", label, re.I)
                else "index"
                if re.search(r"index", label, re.I)
                else "section"
            )
        )
        entry = {
            "node": node,
            "id": key,
            "role": role,
            "label": label,
            "short": label,
            "abbr": ("Ch. " + number) if number else label[:24],
            "number": number,
            "heading_node": chapter[0] if chapter else None,
            "file": node_features.name.v(node),
        }
        sections.append(entry)
        file_map[entry["file"]] = key
    anchor_map, anchor_by_node, node_records = {}, {}, []
    for section in sections:
        anchor_count = 0
        for node in descendants(section["node"]):
            source_id = node_features.id.v(node)
            if source_id:
                if (section["file"], source_id) in anchor_map:
                    raise ValueError("Duplicate source anchor identity")
                anchor_count += 1
                anchor_id = "anchor-" + str(anchor_count)
                anchor_map[(section["file"], source_id)] = (section["id"], anchor_id)
                anchor_by_node[node] = anchor_id
            node_records.append(
                {
                    "tf_node": node,
                    "source_path": node_features.source_path.v(node),
                    "source_file": section["file"],
                    "source_id": source_id,
                    "document_id": section["id"],
                    "anchor": anchor_by_node.get(node),
                }
            )

    def normalize_link(href, section):
        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            return href
        path = (
            posixpath.normpath(
                posixpath.join(posixpath.dirname(section["file"]), unquote(parts.path))
            )
            if parts.path
            else section["file"]
        )
        if parts.query:
            raise ValueError("Queried internal content links are unsupported")
        if parts.fragment:
            if (path, unquote(parts.fragment)) not in anchor_map:
                raise ValueError("Local link selects a missing content anchor")
            destination, anchor = anchor_map[(path, unquote(parts.fragment))]
            return (destination + ".usx" if destination != section["id"] else "") + "#" + anchor
        if path not in file_map:
            raise ValueError("Local link selects unsupported non-spine content or asset")
        return file_map[path] + ".usx"

    styles_root = etree.Element("stylesheet", version="1.0", profile="corpora")
    signatures = {}
    style_counts = defaultdict(int)
    style_records = []

    def presentation(element, node, semantic, node_type):
        element.set(Q + "semantic", semantic)
        element.set(Q + "node-type", node_type)
        values = css_by_node.get(node, {})
        # Intrinsic semantic presentation survives without explicit stylesheet rules.
        values = dict(values)
        if semantic == "bold":
            values.setdefault("font-weight", "bold")
        if semantic == "italic":
            values.setdefault("font-style", "italic")
        states = state_by_node.get(node, {})
        signature = (
            semantic,
            node_type,
            tuple(sorted(values.items())),
            json.dumps(states, sort_keys=True),
        )
        if signature not in signatures:
            style_counts[semantic] += 1
            style_id = semantic + "-" + str(style_counts[semantic])
            signatures[signature] = style_id
            style = etree.SubElement(
                styles_root,
                "style",
                id=style_id,
                publishable="true",
                versetext="false",
                semantic=semantic,
                nodeType=node_type,
            )
            etree.SubElement(style, "name").text = semantic.replace("-", " ").title()
            etree.SubElement(style, "description").text = "Presentation for " + semantic
            for name, value in sorted(values.items()):
                property_element(style, name, value)
            for state, properties in sorted(states.items()):
                for name, value in sorted(properties.items()):
                    property_element(style, name, value, state)
        element.set(Q + "style-id", signatures[signature])
        if node in anchor_by_node:
            element.set("link-id" if element.tag == "char" else Q + "id", anchor_by_node[node])
        style_records.append(
            {
                "tf_node": node,
                "style_id": signatures[signature],
                "source_class": node_features.__getattribute__("class").v(node),
                "source_style": node_features.style.v(node),
            }
        )

    roots = []
    for section in sections:
        root = etree.Element(
            Q + "document",
            nsmap={"cx": CX},
            version="0.1.0",
            id=section["id"],
            type="book",
            profile="general",
            work=work_id,
            lang=metadata_values.get("language", ["und"])[0],
        )
        etree.SubElement(root, Q + "title").text = section["label"]
        if section["role"] == "chapter":
            chapter = etree.SubElement(
                root,
                "chapter",
                number=str(section["number"]),
                style="c",
                sid=work_id + ":" + section["id"],
            )
            heading_node = section["heading_node"]
            presentation(chapter, heading_node, "chapter", "chapter")
            chapter.attrib.pop(Q + "id", None)
        else:
            etree.SubElement(
                root,
                Q + "boundary",
                unit="section",
                scheme="corpora-book-sections",
                sid=section["id"],
                label=section["label"],
            )

        def is_note(node):
            return bool(
                set((node_features.type.v(node) or "").split()) & {"footnote", "endnote"}
                or node_features.role.v(node) in {"doc-footnote", "doc-endnote"}
                or set((node_features.__getattribute__("class").v(node) or "").split())
                & {"mnote", "footnote", "endnote", "note", "tei-notetext"}
            )

        def inline(node, section=section):
            tag = node_features.tag.v(node)
            if tag == "text":
                return [text(node)]
            content = [value for child in kids(node) for value in inline(child)]
            if not kids(node):
                content = [text(node)]
            if is_note(node):
                element = etree.Element("note", style="f", caller="*")
                presentation(element, node, "footnote", "note")
                note_text = etree.SubElement(element, "char", style="ft")
                note_text.set(Q + "semantic", "text")
                note_text.set(Q + "node-type", "text")
                for value in content:
                    append(note_text, value)
                return [element]
            if tag == "br":
                element = etree.Element("optbreak")
                presentation(element, node, "break", "point")
                return [element]
            if tag in {"img", "image"}:
                href = node_features.src.v(node) or node_features.href.v(node)
                from ._cusx_source import local_path

                path = local_path(section["file"], href or "")
                if path not in asset_map:
                    raise ValueError("Image selects a missing or unsupported asset")
                element = etree.Element(
                    "figure",
                    style="fig",
                    file="../../"
                    + asset_map[path]
                    + (("#" + urlsplit(href).fragment) if urlsplit(href).fragment else ""),
                    alt=node_features.alt.v(node) or "",
                )
                presentation(element, node, "figure", "figure")
                return [element]
            if tag == "svg" and any(
                node_features.tag.v(n) not in {"svg", "image", "text"}
                or (node_features.tag.v(n) == "text" and text(n).strip())
                for n in descendants(node)
            ):
                raise ValueError("Complex inline SVG requires a supported adapter")
            if tag in {"p", "blockquote", "li", "dt", "dd", "pre"} or re.fullmatch(
                r"h[1-6]", tag or ""
            ):
                semantic = tag if re.fullmatch(r"h[1-6]", tag) else "paragraph"
                element = etree.Element("char", style="no")
                presentation(
                    element, node, semantic, "section" if semantic.startswith("h") else "paragraph"
                )
                for value in content:
                    append(element, value)
                return [element]
            inline_styles = {
                "i": ("it", "italic"),
                "em": ("it", "italic"),
                "b": ("bd", "bold"),
                "strong": ("bd", "bold"),
                "sup": ("sup", "superscript"),
                "a": ("jmp", "link"),
                "span": ("no", "text"),
                "u": ("no", "text"),
                "small": ("no", "text"),
                "code": ("no", "text"),
                "sub": ("no", "text"),
            }
            if tag in inline_styles:
                style, semantic = inline_styles[tag]
                if tag == "a" and "scripRef" in (
                    node_features.__getattribute__("class").v(node) or ""
                ):
                    semantic = "reference"
                if tag == "a" and not node_features.href.v(node):
                    semantic = "anchor"
                element = etree.Element("char", style=style)
                presentation(element, node, semantic, "link" if tag == "a" else "text")
                if tag == "a" and node_features.href.v(node):
                    element.set("link-href", normalize_link(node_features.href.v(node), section))
                for value in content:
                    append(element, value)
                return [element]
            if node in anchor_by_node:
                anchor = etree.Element("char", style="jmp", **{"link-id": anchor_by_node[node]})
                anchor.set(Q + "semantic", "anchor")
                anchor.set(Q + "node-type", "point")
                return [anchor, *content]
            return content

        def blocks(node, root=root):
            tag = node_features.tag.v(node)
            if (
                tag == "dl"
                and "tei-list-footnotes"
                in (node_features.__getattribute__("class").v(node) or "").split()
            ):
                children = kids(node)
                position = 0
                if node in anchor_by_node:
                    para = etree.SubElement(root, "para", style="p")
                    etree.SubElement(para, "char", style="jmp", **{"link-id": anchor_by_node[node]})
                while position < len(children):
                    child = children[position]
                    if node_features.tag.v(child) == "text":
                        blocks(child)
                        position += 1
                        continue
                    if node_features.tag.v(child) != "dt":
                        raise ValueError("Unsupported footnote-list label structure")
                    label_nodes = [child]
                    position += 1
                    while (
                        position < len(children)
                        and node_features.tag.v(children[position]) == "text"
                    ):
                        label_nodes.append(children[position])
                        position += 1
                    if position >= len(children) or node_features.tag.v(children[position]) != "dd":
                        raise ValueError("Footnote label has no corresponding body")
                    body_node = children[position]
                    position += 1
                    para = etree.SubElement(root, "para", style="p")
                    note = etree.SubElement(para, "note", style="f", caller="*")
                    presentation(note, body_node, "footnote", "note")
                    ft = etree.SubElement(note, "char", style="ft")
                    ft.set(Q + "semantic", "text")
                    ft.set(Q + "node-type", "text")
                    for label_node in label_nodes:
                        for value in inline(label_node):
                            append(ft, value)
                    for body_child in kids(body_node):
                        for value in inline(body_child):
                            append(ft, value)
                    if not kids(body_node):
                        append(ft, text(body_node))
                return
            if tag == "table":
                table = etree.SubElement(root, "table")
                presentation(table, node, "table", "table")

                def table_children(parent, source_node):
                    for child in kids(source_node):
                        kind = node_features.tag.v(child)
                        if kind == "text":
                            if text(child).strip():
                                raise ValueError("Text outside table rows is unsupported")
                            append(parent, text(child))
                        elif kind in {"thead", "tbody", "tfoot"}:
                            table_children(parent, child)
                        elif kind == "tr":
                            row = etree.Element("row", style="tr")
                            presentation(row, child, "row", "row")
                            column = 1
                            for cell_node in kids(child):
                                cell_tag = node_features.tag.v(cell_node)
                                if cell_tag == "text":
                                    if text(cell_node).strip():
                                        raise ValueError("Text outside table cells is unsupported")
                                    append(row, text(cell_node))
                                    continue
                                if cell_tag not in {"td", "th"} or node_features.rowspan.v(
                                    cell_node
                                ) not in {
                                    None,
                                    "1",
                                }:
                                    raise ValueError("Unsupported table cell or row span")
                                cell = etree.Element(
                                    "cell",
                                    style=("th" if cell_tag == "th" else "tc") + str(column),
                                    align="start",
                                )
                                presentation(cell, cell_node, "cell", "cell")
                                span = node_features.colspan.v(cell_node)
                                if span:
                                    if not span.isdecimal() or int(span) < 1:
                                        raise ValueError("Invalid table column span")
                                    cell.set("colspan", span)
                                column += int(span or "1")
                                for value in inline(cell_node):
                                    append(cell, value)
                                row.append(cell)
                            parent.append(row)
                        elif kind == "caption":
                            row = etree.Element("row", style="tr")
                            cell = etree.SubElement(row, "cell", style="th1", align="start")
                            presentation(cell, child, "cell", "cell")
                            for value in inline(child):
                                append(cell, value)
                            parent.append(row)
                        else:
                            raise ValueError("Unsupported table structure")

                table_children(table, node)
                return
            if not is_note(node) and (
                tag == "p"
                or tag in {"blockquote", "li", "pre", "dt", "dd"}
                or re.fullmatch(r"h[1-6]", tag or "")
            ):
                semantic = tag if re.fullmatch(r"h[1-6]", tag) else "paragraph"
                style = "s" + str(min(int(tag[1:]), 3)) if re.fullmatch(r"h[1-6]", tag) else "p"
                paragraph = etree.SubElement(root, "para", style=style)
                presentation(
                    paragraph,
                    node,
                    semantic,
                    "section" if re.fullmatch(r"h[1-6]", tag) else "paragraph",
                )
                for value in [value for child in kids(node) for value in inline(child)]:
                    append(paragraph, value)
            elif is_note(node) or tag == "text" or tag == "hr":
                paragraph = etree.SubElement(root, "para", style="b" if tag == "hr" else "p")
                if tag == "hr":
                    presentation(paragraph, node, "break", "point")
                elif tag == "text":
                    presentation(paragraph, node, "text", "text")
                    append(paragraph, text(node))
                else:
                    for value in inline(node):
                        append(paragraph, value)
            elif tag in {
                "img",
                "image",
                "svg",
                "a",
                "b",
                "strong",
                "i",
                "em",
                "span",
                "sup",
                "sub",
                "br",
                "code",
                "u",
                "small",
            }:
                paragraph = etree.SubElement(root, "para", style="p")
                for value in inline(node):
                    append(paragraph, value)
            elif kids(node):
                if node in anchor_by_node:
                    paragraph = etree.SubElement(root, "para", style="p")
                    anchor = etree.SubElement(
                        paragraph, "char", style="jmp", **{"link-id": anchor_by_node[node]}
                    )
                    anchor.set(Q + "semantic", "anchor")
                    anchor.set(Q + "node-type", "point")
                for child in kids(node):
                    blocks(child)
            else:
                paragraph = etree.SubElement(root, "para", style="p")
                for value in inline(node):
                    append(paragraph, value)

        blocks(section["node"])
        if section["role"] == "chapter":
            etree.SubElement(root, "chapter", eid=work_id + ":" + section["id"])
        else:
            etree.SubElement(
                root,
                Q + "boundary",
                unit="section",
                scheme="corpora-book-sections",
                eid=section["id"],
            )
        original_text = "".join("".join(p.itertext()) for p in root if p.tag in {"para", "table"})
        if original_text != text(section["node"]):
            raise ValueError("Export text differs from Text-Fabric before whitespace normalization")
        normalize_content(root)
        published_text = "".join("".join(p.itertext()) for p in root if p.tag in {"para", "table"})
        if re.sub(r"\s+", "", published_text) != re.sub(r"\s+", "", original_text):
            raise ValueError("Whitespace normalization changed non-whitespace characters")
        write_xml(usx_dir / (section["id"] + ".usx"), root)
        (json_dir / (section["id"] + ".json")).write_text(
            json.dumps(encode(root), ensure_ascii=False, indent=2) + "\n"
        )
        roots.append(root)
    write_xml(package / "release/styles.xml", styles_root, pretty=True)

    metadata = etree.Element("CorporaMetadata", version="0.1.0", id=work_id, revision="1")
    identification = etree.SubElement(metadata, "identification")
    etree.SubElement(identification, "name").text = title
    if metadata_values.get("description"):
        etree.SubElement(identification, "description").text = metadata_values["description"][0]
    etree.SubElement(identification, "scope").text = "Book"
    content_type = etree.SubElement(metadata, "type")
    for name, value in [("medium", "text"), ("documentType", "book"), ("hasCharacters", "true")]:
        etree.SubElement(content_type, name).text = value
    language = etree.SubElement(metadata, "language")
    etree.SubElement(language, "ldml").text = metadata_values.get("language", ["und"])[0]
    format_ = etree.SubElement(metadata, "format")
    for name, value in [
        ("usxVersion", "3.0"),
        ("corporaVersion", "0.1.0"),
        ("versedParagraphs", "false"),
    ]:
        etree.SubElement(format_, name).text = value
    names = etree.SubElement(metadata, "names")
    for section in sections:
        name = etree.SubElement(names, "name", id=section["id"])
        for tag in ["abbr", "short"]:
            etree.SubElement(name, tag).text = section[tag]
        etree.SubElement(name, "long").text = section["label"]
    source = etree.SubElement(metadata, "source")
    publication_element = etree.SubElement(
        etree.SubElement(metadata, "publications"), "publication", id="p1", default="true"
    )
    etree.SubElement(publication_element, "name").text = title
    for field, output in [
        ("publisher", "publisher"),
        ("creator", "creator"),
        ("identifier", "identifier"),
        ("subject", "subject"),
        ("date", "datePublished"),
    ]:
        for value in metadata_values.get(field, []):
            etree.SubElement(publication_element, output).text = value
    depths = {}
    for path, _label, depth in publication.navigation:
        depths.setdefault(path, depth)
    for owner in (source, publication_element):
        structure = etree.SubElement(owner, "structure")
        stack = []
        for section in sections:
            depth = depths.get(section["file"], 0)
            while stack and stack[-1][0] >= depth:
                stack.pop()
            parent = stack[-1][1] if stack else structure
            entry = etree.SubElement(
                parent,
                "content",
                name=section["id"],
                src="release/USX_1/" + section["id"] + ".usx",
                role=section["role"],
            )
            stack.append((depth, entry))
    statements = list(metadata_values.get("rights", []))
    for section in sections:
        for node in descendants(section["node"]):
            value = text(node).strip()
            if (
                "footer" in (node_features.__getattribute__("class").v(node) or "").split()
                and re.search(r"copyright|©|all rights reserved", value, re.I)
                and value not in statements
            ):
                statements.append(value)
    if statements:
        statement = etree.SubElement(
            etree.SubElement(etree.SubElement(metadata, "copyright"), "fullStatement"),
            "statementContent",
            type="xhtml",
        )
        for value in statements:
            etree.SubElement(statement, "p").text = value
    license_ = etree.Element("license", id=work_id, profile="corpora")
    for value in statements or ["No rights statement was supplied."]:
        etree.SubElement(license_, "statement").text = value
    etree.SubElement(license_, "publicationRights", status="unspecified")
    write_xml(package / "license.xml", license_, pretty=True)
    manifest = etree.SubElement(metadata, "manifest")
    for file in sorted(package.rglob("*")):
        if file.is_file() and file.name != "metadata.xml":
            data = file.read_bytes()
            mime = (
                "application/xml"
                if file.suffix in {".xml", ".usx"}
                else mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            )
            mime = asset_mime.get(file.relative_to(package).as_posix(), mime)
            etree.SubElement(
                manifest,
                "resource",
                checksum=hashlib.sha256(data).hexdigest(),
                checksumAlgorithm="sha256",
                mimeType=mime,
                size=str(len(data)),
                uri=file.relative_to(package).as_posix(),
            )
    write_xml(package / "metadata.xml", metadata, pretty=True)
    schema = grammar()
    for section, root in zip(sections, roots, strict=True):
        validate(usx_dir / (section["id"] + ".usx"), schema)
        restored = decode(json.loads((json_dir / (section["id"] + ".json")).read_text()))
        if not schema.validate(restored) or encode(restored) != encode(root):
            raise ValueError("JSON round-trip differs")
    return {
        "content_mappings": [
            {
                "source": s["file"],
                "document_id": s["id"],
                "role": s["role"],
                "src": "release/USX_1/" + s["id"] + ".usx",
            }
            for s in sections
        ],
        "node_mappings": node_records,
        "style_mappings": style_records,
        "style_diagnostics": style_diagnostics,
        "source_stylesheets": source_style_sheets,
        "bibliographic_evidence": metadata_values,
        "tf_slots": node_features.otype.maxSlot,
        "tf_nodes": node_features.otype.maxNode,
        "characters": sum(len(text(s["node"])) for s in sections),
        "published_characters": sum(
            len("".join(p.itertext())) for r in roots for p in r if p.tag in {"para", "table"}
        ),
        "whitespace_policy": "collapse-whitespace-runs-trim-flows-omit-empty-content",
        "non_whitespace_text_match": True,
        "notes": sum(len(r.findall(".//note")) for r in roots),
    }
