"""Conservative source adapters. Explicit mappings govern ambiguous semantics."""

import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree, html

from .encoding import XML, local_path, node, source_text, xml

EPUB = "http://www.idpf.org/2007/ops"
MAX_BYTES = 256 * 1024 * 1024


def archive_bytes(source):
    with zipfile.ZipFile(source) as z:
        names = z.namelist()
        if len(set(names)) != len(names) or sum(i.file_size for i in z.infolist()) > MAX_BYTES:
            raise ValueError("duplicate or oversized archive")
        for name in names:
            if local_path("root", name) != name.rstrip("/") or name.startswith("/"):
                raise ValueError("unsafe source archive member")
        return {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}


def tag(e):
    return etree.QName(e).localname if isinstance(e.tag, str) else "comment"


def normalized(s):
    return re.sub(r"[\t\r\n ]+", " ", s).strip(" ")


def source_coverage(roots, members, policy):
    """Derive semantic coverage from original DOMs, independently of HtmlMapper.

    This traversal never observes the mapped nodes or mapper asset inventory.
    It detects omitted/reclassified notes, dropped figures and altered alt text
    even when the surviving reading text happens to remain unchanged.
    """
    notes, images, alts, abbreviations = [], [], [], []
    tables = 0
    for path, root in roots:
        for e in root.iter():
            if not isinstance(e.tag, str):
                continue
            if tag(e) == "abbr":
                abbreviations.append([normalized(raw_reading(e, policy)), e.get("title")])
            if tag(e) == "div" and "footnote" in e.get("class", "").split():
                notes.append(
                    hashlib.sha256(normalized(raw_reading(e, policy)).encode()).hexdigest()
                )
            if tag(e) == "dl" and policy.get("definitionListsAreNotes"):
                children = list(e)
                for i in range(0, len(children), 2):
                    text = normalized(
                        raw_reading(children[i], policy) + raw_reading(children[i + 1], policy)
                    )
                    notes.append(hashlib.sha256(text.encode()).hexdigest())
            if tag(e) == "table" and e.xpath(".//*[local-name()='tr' or local-name()='row']"):
                tables += 1
            if tag(e) in {"img", "image"}:
                src = e.get("src") or e.get("{http://www.w3.org/1999/xlink}href")
                assetpath = local_path(path, urlsplit(src).path)
                images.append(hashlib.sha256(members[assetpath]).hexdigest())
                if e.get("alt"):
                    alts.append(e.get("alt"))
    assets = set(images)
    if policy.get("retainUnreferencedImages"):
        assets.update(
            hashlib.sha256(b).hexdigest()
            for p, b in members.items()
            if p.lower().endswith((".jpg", ".jpeg", ".png"))
        )
    return {
        "sourceNoteHashes": notes,
        "sourceTableCount": tables,
        "sourceGraphicHashes": images,
        "sourceAltText": alts,
        "sourceAssetHashes": sorted(assets),
        "sourceAbbreviationsSha256": hashlib.sha256(
            json.dumps(abbreviations, ensure_ascii=False).encode()
        ).hexdigest(),
        "sourceAbbreviationCount": len(abbreviations),
    }


class HtmlMapper:
    def __init__(self, members, policy):
        self.members = members
        self.policy = policy
        self.assets = {}
        self.excluded = []
        self.warnings = Counter()
        self.aliases = {}
        self.pending_refs = []
        self.serial = 0

    def ident(self, path, value):
        key = path + "#" + value
        return "s-" + hashlib.sha256(key.encode()).hexdigest()[:16]

    def sid(self, e, path, n):
        if e.get("id") or e.get("name"):
            value = e.get("id") or e.get("name")
            n["id"] = self.ident(path, value)
            if path + "#" + value in self.aliases:
                raise ValueError("duplicate HTML source ID")
            self.aliases[path + "#" + value] = n["id"]
        return n

    def skip(self, e):
        classes = set(e.get("class", "").split())
        excluded = tag(e) in {"script", "style", "comment"} or bool(
            classes & set(self.policy.get("excludeClasses", []))
        )
        if excluded:
            self.excluded.append(
                {
                    "tag": tag(e),
                    "id": e.get("id"),
                    "class": e.get("class"),
                    "text": "".join(e.itertext()),
                }
            )
        return excluded

    def text(self, value):
        # Preserve NBSP and combining marks. Reflow only ASCII formatting whitespace.
        return re.sub(r"[\t\r\n ]+", " ", value) if value is not None else None

    def children(self, e, path, n):
        n["text"] = self.text(e.text)
        for c in e:
            if self.skip(c):
                if c.get("id"):
                    n["children"].append(self.sid(c, path, node("anchor")))
                self.append_text(n, self.text(c.tail))
                continue
            mapped = self.inline(c, path)
            if mapped is None:
                raise ValueError("unsupported mixed content: " + tag(c))
            if isinstance(mapped, list):
                for item in mapped:
                    n["children"].append(item)
            else:
                n["children"].append(mapped)
            self.append_text(n, self.text(c.tail))
        return n

    @staticmethod
    def append_text(n, text):
        if text:
            if n["children"]:
                n["children"][-1]["tail"] = (n["children"][-1].get("tail") or "") + text
            else:
                n["text"] = (n.get("text") or "") + text

    def inline(self, e, path):
        t = tag(e)
        attrs = {}
        if e.get(f"{{{XML}}}lang") or e.get("lang"):
            attrs[f"{{{XML}}}lang"] = e.get(f"{{{XML}}}lang") or e.get("lang")
        if t in {"em", "strong"}:
            mapped = "emph"
        elif t == "abbr":
            abbreviation = self.children(e, path, node("abbr"))
            if "title" not in e.attrib:
                abbreviation["attrs"] = attrs
                return self.sid(e, path, abbreviation)
            # The attribute supplies the alternative verbatim; do not infer,
            # normalize or substitute it into the displayed reading text.
            choice = self.sid(e, path, node("choice", **attrs))
            choice["children"] = [abbreviation, node("expan", e.get("title"))]
            return choice
        elif t in {"i", "b", "small", "sup", "sub", "u", "hi"}:
            mapped = "hi"
            attrs["rend"] = {
                "i": "italic",
                "b": "bold",
                "small": "smallcaps",
                "sup": "superscript",
                "sub": "subscript",
                "u": "underline",
            }.get(t, e.get("type", "italic"))
            if attrs["rend"] not in {
                "italic",
                "bold",
                "smallcaps",
                "superscript",
                "subscript",
                "underline",
            }:
                raise ValueError("unknown declared typography: " + attrs["rend"])
        elif t in {"a", "reference"}:
            if t == "reference" or e.get("href") or e.get("osisRef"):
                mapped = "ref"
                target = e.get("href") or (
                    "urn:source-osis:" + e.get("osisRef")
                    if e.get("osisRef")
                    else "urn:source-reference:unresolved"
                )
                attrs["target"] = target
                attrs["type"] = "unresolved"
            else:
                return self.unwrap(e, path)
        elif t in {"q", "quote", "blockquote"}:
            mapped = "quote"
        elif t in {"img", "image"}:
            target = e.get("src") or e.get("{http://www.w3.org/1999/xlink}href")
            if not target:
                raise ValueError("image missing source")
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                raise ValueError("remote image unavailable; no automatic fetching")
            src = local_path(path, parts.path)
            if src not in self.members:
                raise ValueError("substantive image unavailable: " + src)
            dest = (
                "assets/"
                + hashlib.sha256(self.members[src]).hexdigest()[:16]
                + Path(src).suffix.lower()
            )
            self.assets[dest] = self.members[src]
            fig = self.sid(e, path, node("figure"))
            fig["children"].append(node("graphic", url=dest))
            if e.get("alt"):
                fig["children"].append(node("figDesc", e.get("alt")))
            return fig
        elif t == "br":
            # Break is deliberately prose reflow; poetry needs a declared line mapping.
            self.warnings["br reflowed to space; no poetry semantics inferred"] += 1
            return {"tag": "anchor", "text": None, "attrs": {}, "children": [], "tail": " "}
        elif t in {"span", "font", "cite", "code", "dfn"}:
            # An unclassified span has no semantic evidence. Keep its identity/text
            # in a standard quote-free inline wrapper with only typographic evidence.
            style = e.get("style", "")
            classes = e.get("class", "")
            rendition = next(
                (
                    v
                    for k, v in [
                        ("italic", "italic"),
                        ("bold", "bold"),
                        ("small-caps", "smallcaps"),
                    ]
                    if k in style or k in classes
                ),
                None,
            )
            if attrs.get(f"{{{XML}}}lang"):
                mapped = "foreign"
            elif rendition:
                mapped, attrs["rend"] = "hi", rendition
            else:
                return self.unwrap(e, path)
        elif t in {"p", "table", "ul", "ol", "li", "div", "dl", "dd", "dt", "section"}:
            return self.block(e, path)
        else:
            raise ValueError("unsupported HTML element: " + t)
        n = self.sid(e, path, node(mapped, **attrs))
        self.children(e, path, n)
        if mapped == "ref":
            self.pending_refs.append((path, n))
        return n

    def unwrap(self, e, path):
        n = self.children(e, path, node("hi", rend="italic"))
        children = []
        if e.get("id") or e.get("name"):
            children.append(self.sid(e, path, node("anchor")))
        if n.get("text"):
            if children:
                children[-1]["tail"] = n["text"]
            else:
                children.append(
                    {"tag": "anchor", "attrs": {}, "children": [], "text": None, "tail": n["text"]}
                )
        children.extend(n["children"])
        return children

    def block(self, e, path):
        t = tag(e)
        classes = set(e.get("class", "").split())
        if t == "div" and "poetry" in classes:
            n = self.sid(e, path, node("lg"))
            for c in e:
                if "verse" not in c.get("class", "").split():
                    raise ValueError("unknown poetry line structure")
                n["children"].append(self.children(c, path, self.sid(c, path, node("l"))))
            return n
        if t == "svg":
            imgs = e.findall("{*}image")
            if len(imgs) != 1 or any(tag(c) != "image" for c in e):
                raise ValueError("non-wrapper SVG requires dedicated source asset mapping")
            return self.inline(imgs[0], path)
        if t == "dl" and self.policy.get("definitionListsAreNotes"):
            children = list(e)
            if len(children) % 2 or any(
                tag(c) != ("dt" if i % 2 == 0 else "dd") for i, c in enumerate(children)
            ):
                raise ValueError("malformed source note label/body pairs")
            result = []
            for i in range(0, len(children), 2):
                n = node("note")
                n["children"] = [
                    self.children(children[i], path, self.sid(children[i], path, node("p"))),
                    *self.blocks(children[i + 1], path),
                ]
                result.append(n)
            return result
        if t in {"p", "dt"}:
            return self.children(e, path, self.sid(e, path, node("p")))
        if t in {"div", "dd"} and ("footnote" in classes or t == "dd"):
            n = self.sid(e, path, node("note"))
            n["children"] = self.blocks(e, path)
            return n
        if t in {"ul", "ol", "list"}:
            n = self.sid(e, path, node("list", type="ordered" if t == "ol" else "unordered"))
            for c in e:
                if tag(c) != "li":
                    raise ValueError("list contains non-item")
                n["children"].append(self.children(c, path, self.sid(c, path, node("item"))))
            return n
        if t == "table":
            n = self.sid(e, path, node("table"))
            for row in e.xpath(
                "./*[local-name()='tr' or local-name()='row']|./*[local-name()='tbody' or local-name()='thead' or local-name()='tfoot']/*"
            ):
                rn = self.sid(row, path, node("row"))
                for cell in row:
                    if tag(cell) not in {"td", "th", "cell"}:
                        raise ValueError("unknown table cell")
                    at = {"role": "label" if tag(cell) == "th" else "data"}
                    for src, dest in (("colspan", "cols"), ("rowspan", "rows")):
                        if cell.get(src):
                            at[dest] = cell.get(src)
                    cn = self.children(cell, path, self.sid(cell, path, node("cell", **at)))
                    rn["children"].append(cn)
                n["children"].append(rn)
            if not n["children"]:
                self.warnings["empty source table retained as evidence, has no reading cells"] += 1
                return self.sid_empty_table(n)
            if self.policy.get("normalizeRaggedHtmlTables"):
                widths = [
                    sum(int(c["attrs"].get("cols", "1")) for c in row["children"])
                    for row in n["children"]
                ]
                if any(c["attrs"].get("rows") for row in n["children"] for c in row["children"]):
                    raise ValueError("ragged rowspan table requires explicit grid mapping")
                for row, width in zip(n["children"], widths, strict=True):
                    if width < max(widths):
                        self.warnings[
                            "implicit trailing HTML table cells made explicit as empty cells"
                        ] += max(widths) - width
                        row["children"].extend(
                            node("cell", role="data") for _ in range(max(widths) - width)
                        )
            return n
        if t in {"blockquote", "quote"} or (t == "div" and "blockquote" in classes):
            n = self.sid(e, path, node("quote"))
            n["children"] = self.blocks(e, path)
            return n
        if t in {"img", "figure"}:
            if t == "img":
                return self.inline(e, path)
            n = self.sid(e, path, node("figure"))
            for c in e:
                if tag(c) == "figcaption":
                    n["children"].append(self.children(c, path, node("head")))
                elif tag(c) == "img":
                    n["children"].extend(self.inline(c, path)["children"])
                else:
                    raise ValueError("unknown figure component")
            return n
        if t in {"div", "section", "dl", "li", "dd", "nav"}:
            n = self.sid(e, path, node("div", type="section"))
            n["children"] = self.blocks(e, path)
            return n
        if re.fullmatch(r"h[1-6]", t) or t == "title":
            return self.children(e, path, self.sid(e, path, node("head")))
        if t in {"hr"}:
            return self.sid(e, path, node("p"))
        if t == "pre":
            self.warnings["pre source ASCII whitespace reflowed"] += 1
            return self.children(e, path, self.sid(e, path, node("p")))
        return self.inline(e, path)

    @staticmethod
    def sid_empty_table(n):
        # Empty table contributes no text; preserve its ID as empty paragraph.
        return {**n, "tag": "p", "attrs": {}}

    def blocks(self, container, path):
        result = []
        pending = (
            node("p", self.text(container.text))
            if container.text and container.text.strip()
            else None
        )
        block_tags = {
            "p",
            "div",
            "section",
            "dl",
            "dd",
            "dt",
            "li",
            "ul",
            "ol",
            "table",
            "blockquote",
            "quote",
            "img",
            "figure",
            "svg",
            "pre",
            "nav",
            "hr",
            "title",
        }
        for c in container:
            is_block = tag(c) in block_tags or bool(re.fullmatch(r"h[1-6]", tag(c)))
            if self.skip(c):
                if c.get("id"):
                    if pending is None:
                        pending = node("p")
                    pending["children"].append(self.sid(c, path, node("anchor")))
            elif is_block:
                if pending is not None:
                    result.append(pending)
                    pending = None
                mapped = self.block(c, path)
                result.extend(mapped if isinstance(mapped, list) else [mapped])
            else:
                if pending is None:
                    pending = node("p")
                mapped = self.inline(c, path)
                pending["children"].extend(mapped if isinstance(mapped, list) else [mapped])
            if c.tail and (c.tail.strip() or pending is not None):
                if pending is None:
                    pending = node("p")
                self.append_text(pending, self.text(c.tail))
        if pending is not None:
            result.append(pending)
        return result

    def resolve(self):
        for path, ref in self.pending_refs:
            target = ref["attrs"]["target"]
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                continue
            dest = local_path(path, parts.path) if parts.path else path
            key = dest + "#" + parts.fragment
            if key in self.aliases:
                ref["attrs"]["target"] = "#" + self.aliases[key]
            else:
                # Scope unresolved local links to source URI rather than fabricate TEI targets.
                ref["attrs"]["target"] = "urn:source-local:" + key


def headings_to_divs(blocks, level=1, *, kind="chapter"):
    """Declared top heading level, no arbitrary XHTML/file boundaries."""
    result, current = [], None
    for n in blocks:
        depth = n.pop("headingLevel", None)
        if depth == level:
            current = node("div", type=kind)
            current["children"].append(n)
            result.append(current)
        elif current is not None:
            if n["tag"] == "head":
                sec = node("div", type="section")
                sec["children"].append(n)
                current["children"].append(sec)
                # Subsequent paragraphs should belong to this section.
                current = sec
            else:
                current["children"].append(n)
        else:
            result.append(n)
    return result


def html_root(data, *, fragment=False):
    if fragment:
        return xml(b"<source>" + data + b"</source>")
    # HTML parser is deterministic but source repair must be reported/compared.
    parser = html.HTMLParser(no_network=True, remove_comments=True)
    # Inputs to this bounded adapter are UTF-8. Do not let HTML's legacy
    # fallback misdecode decomposed marks in files without a charset meta tag.
    root = html.fromstring(data.decode("utf-8"), parser=parser)
    return root.find("body") if root.find("body") is not None else root


def load_html(source, declared):
    if not declared:
        raise ValueError("HTML requires work and structure policy sidecar")
    if source.suffix == ".zip":
        members = archive_bytes(source)
        paths = [n for n in members if n.lower().endswith((".htm", ".html"))]
        if len(paths) != 1:
            raise ValueError("ZIP requires exactly one HTML source in this bounded adapter")
        path = paths[0]
    else:
        path = source.name
        members = {path: source.read_bytes()}
    root = html_root(members[path], fragment=declared.get("xmlFragment", False))
    mapper = HtmlMapper(members, declared)
    blocks = mapper.blocks(root, path)
    # Heading levels live in source markup and are recorded before transformation.
    heads = [e for e in root.iter() if re.fullmatch(r"h[1-6]", tag(e)) or tag(e) == "title"]
    mapped_heads = []

    def collect(n):
        if n["tag"] == "head":
            mapped_heads.append(n)
        for c in n["children"]:
            collect(c)

    for n in blocks:
        collect(n)
    if len(heads) != len(mapped_heads):
        raise ValueError("source heading coverage mismatch")
    for e, n in zip(heads, mapped_heads, strict=True):
        n["headingLevel"] = int(e.get("level", tag(e)[1:] if tag(e).startswith("h") else "0"))
    # Fragment sources have flat title levels; ordinary HTML has explicit h3 chapters.
    model = structured_blocks(blocks, declared)
    conform_divisions(model)
    mapper.resolve()
    if declared.get("retainUnreferencedImages"):
        for assetpath, data in members.items():
            if assetpath.lower().endswith((".jpg", ".jpeg", ".png")):
                dest = (
                    "assets/"
                    + hashlib.sha256(data).hexdigest()[:16]
                    + Path(assetpath).suffix.lower()
                )
                mapper.assets[dest] = data
    return (
        {"work": declared["work"], **model},
        mapper.assets,
        {
            "format": "xml-fragment"
            if declared.get("xmlFragment")
            else "html-zip"
            if source.suffix == ".zip"
            else "html",
            "normalization": "ASCII formatting whitespace reflowed; NBSP and Unicode scalars retained",
            "excluded": mapper.excluded,
            "warnings": dict(mapper.warnings),
            "sourceMembers": {p: hashlib.sha256(b).hexdigest() for p, b in members.items()},
            "sourceText": normalized(raw_reading(root, declared)),
            **source_coverage([(path, root)], members, declared),
            "fidelityPolicy": "whole source text compared after whitespace folding; source page markers and scripts/styles excluded; image alt checked separately",
        },
    )


def raw_reading(root, policy):
    excluded = set(policy.get("excludeClasses", []))

    def read(e):
        if tag(e) in {"script", "style", "comment"} or set(e.get("class", "").split()) & excluded:
            return ""
        text = (e.text or "") + "".join(read(c) + (c.tail or "") for c in e)
        block = tag(e) in {
            "p",
            "title",
            "div",
            "td",
            "th",
            "cell",
            "li",
            "dt",
            "dd",
            "blockquote",
            "ul",
            "ol",
            "table",
            "tr",
            "row",
            "pre",
            "section",
            "nav",
        } or re.fullmatch(r"h[1-6]", tag(e))
        return " " + text + " " if block else text

    return read(root)


def structured_blocks(blocks, policy):
    top = policy.get("topHeadingLevel")
    if top is None:
        return {"body": [wrap_heads(n) for n in blocks]}
    # Source may wrap all material in layout divs. Remove these only under explicit policy.
    if policy.get("flattenLayoutDivs"):

        def flatten(n):
            if n["tag"] == "div" and n["attrs"].get("type") == "section":
                prefix = []
                if n.get("id"):
                    p = node("p")
                    p["children"] = [
                        {"tag": "anchor", "id": n["id"], "attrs": {}, "children": [], "text": None}
                    ]
                    prefix = [p]
                return prefix + [x for c in n["children"] for x in flatten(c)]
            return [n]

        blocks = [x for n in blocks for x in flatten(n)]
    front, body, back = [], [], []
    stack = []
    begun = False
    back_labels = set(policy.get("backHeadings", []))
    front_labels = set(policy.get("frontHeadings", []))
    region = "front"
    for n in blocks:
        depth = n.pop("headingLevel", None)
        label = normalized(source_text(n)) if depth is not None else ""
        if depth is not None and (
            label in back_labels
            or any(label.startswith(s) for s in policy.get("backStartsWith", []))
        ):
            depth = top
        if depth == top:
            if label in front_labels or (
                policy.get("bodyStartsWith")
                and not begun
                and not label.startswith(policy["bodyStartsWith"])
            ):
                region = "front"
            elif label in back_labels or any(
                label.startswith(s) for s in policy.get("backStartsWith", [])
            ):
                region = "back"
            else:
                region, begun = "body", True
            target = {"front": front, "body": body, "back": back}[region]
            div = node(
                "div",
                type=policy.get("topType", "chapter")
                if region == "body"
                else "frontmatter"
                if region == "front"
                else "appendix",
            )
            div["children"].append(n)
            target.append(div)
            stack = [(depth, div)]
        elif depth is not None and stack and depth > top:
            while len(stack) > 1 and stack[-1][0] >= depth:
                stack.pop()
            div = node("div", type="section")
            div["children"].append(n)
            stack[-1][1]["children"].append(div)
            stack.append((depth, div))
        elif stack:
            stack[-1][1]["children"].append(wrap_heads(n))
        else:
            front.append(wrap_heads(n))
    # Standalone front/back use explicit divs, keeping all introductions/ordering.
    for nodes, typ in ((front, "frontmatter"), (back, "backmatter")):
        if any(n["tag"] != "div" for n in nodes):
            d = node("div", type=typ)
            d["children"] = nodes[:]
            nodes[:] = [d]
    return {"front": front, "body": body, "back": back}


def wrap_heads(n):
    if n["tag"] == "head":
        d = node("div", type="section")
        d["children"] = [n]
        return d
    return n


def conform_divisions(model):
    """Represent mixed sibling prose/division runs using unheaded standard sections.

    TEI div permits prose followed by subdivisions, but not prose after a subdivision.
    Explicit unheaded groups keep source ordering without inventing a heading or
    incorrectly putting following prose inside a preceding named subsection.
    """
    inline = {"anchor", "hi", "emph", "ref", "unclear", "gap", "choice", "abbr"}

    def fix(n):
        children = n.get("children", [])
        for i, c in enumerate(children):
            if n["tag"] in {"div", "quote", "note"} and c["tag"] in inline:
                p = node("p")
                p["children"] = [c]
                children[i] = p
            fix(children[i])
        if n["tag"] in {"quote", "note"}:

            def flatten(c):
                if c["tag"] == "div":
                    prefix = []
                    if c.get("id"):
                        p = node("p")
                        p["children"] = [
                            {
                                "tag": "anchor",
                                "id": c["id"],
                                "attrs": {},
                                "children": [],
                                "text": None,
                            }
                        ]
                        prefix = [p]
                    return prefix + [x for child in c["children"] for x in flatten(child)]
                return [c]

            children = [x for c in children for x in flatten(c)]
            n["children"] = children
        if n["tag"] == "div" and any(c["tag"] == "div" for c in children):
            groups, run = [], []
            for c in children:
                if c["tag"] == "head" and not groups and not run:
                    groups.append(c)
                elif c["tag"] == "div":
                    if run:
                        section = node("div", type="section")
                        section["children"] = run
                        groups.append(section)
                        run = []
                    groups.append(c)
                else:
                    run.append(c)
            if run:
                section = node("div", type="section")
                section["children"] = run
                groups.append(section)
            n["children"] = groups

    for region in ("front", "body", "back"):
        for n in model.get(region, []):
            fix(n)


def epub_source(source, declared):
    if not declared:
        raise ValueError("EPUB requires explicit structural policy; spine files are not chapters")
    members = archive_bytes(source)
    container = xml(members["META-INF/container.xml"])
    opfpath = container.find(".//{*}rootfile").get("full-path")
    opf = xml(members[opfpath])
    manifest = {
        n.get("id"): (local_path(opfpath, n.get("href")), n)
        for n in opf.findall("{*}manifest/{*}item")
    }
    paths = [manifest[n.get("idref")][0] for n in opf.findall("{*}spine/{*}itemref")]
    if len(set(paths)) != len(paths):
        raise ValueError("repeated EPUB spine requires occurrence mapping")
    mapper = HtmlMapper(members, declared)
    blocks, raw, source_roots = [], [], []
    for path in paths:
        root = xml(members[path])
        body = root.find("{*}body")
        if body is None:
            raise ValueError("EPUB body absent")
        source_roots.append((path, body))
        # Namespace-neutral mapping and source-scoped IDs, preserving inline tails.
        source_heads = [e for e in body.iter() if re.fullmatch(r"h[1-6]", tag(e))]
        mapped = mapper.blocks(body, path)
        hs = []

        def heads(n, inside_figure=False, hs=hs):
            inside_figure = inside_figure or n["tag"] == "figure"
            if n["tag"] == "head" and not inside_figure:
                hs.append(n)
            for c in n["children"]:
                heads(c, inside_figure, hs)

        for n in mapped:
            heads(n)
        if len(hs) != len(source_heads):
            raise ValueError("EPUB heading coverage mismatch")
        for e, n in zip(source_heads, hs, strict=True):
            n["headingLevel"] = int(tag(e)[1])
        blocks.extend(mapped)
        raw.append(raw_reading(body, declared))
    model = structured_blocks(blocks, declared)
    unspined = [
        p
        for p, n in manifest.values()
        if n.get("media-type") == "application/xhtml+xml" and p not in paths
    ]
    if unspined and not declared.get("retainSupplementary"):
        raise ValueError(
            "unmapped non-spine XHTML needs explicit supplementary mapping: " + repr(unspined)
        )
    for path in unspined:
        root = xml(members[path])
        body = root.find("{*}body")
        source_roots.append((path, body))
        n = node("div", type="backmatter")
        n["children"] = mapper.blocks(body, path)
        model.setdefault("back", []).append(n)
        raw.append(raw_reading(body, declared))
    conform_divisions(model)
    mapper.resolve()
    return (
        {"work": declared["work"], **model},
        mapper.assets,
        {
            "format": "epub",
            "spine": paths,
            "sourceText": normalized(" ".join(raw)),
            **source_coverage(source_roots, members, declared),
            "excluded": mapper.excluded,
            "warnings": dict(mapper.warnings),
            "normalization": "ASCII formatting whitespace reflowed; NBSP/combining marks retained",
            "sourceNavigation": [
                p
                for p, n in manifest.values()
                if n.get("properties") == "nav" or n.get("media-type") == "application/x-dtbncx+xml"
            ],
            "splittingEvidence": "explicit source heading levels + reviewed policy; XHTML boundaries ignored",
        },
    )
