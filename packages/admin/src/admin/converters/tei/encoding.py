"""Declared structural mappings to a constrained TEI package (no semantic guessing)."""

from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import re
import shutil
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from lxml import etree, isoschematron

NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
T = {"t": NS}
PROFILE = "corpora-tei/0.1.0"
BASE = Path(__file__).parent
ATOM = {"head", "p", "l", "cell", "item", "figDesc"}
DIV_TYPES = {
    "part",
    "book",
    "surah",
    "chapter",
    "section",
    "introduction",
    "appendix",
    "frontmatter",
    "backmatter",
}
PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ledger_digest(value):
    return {
        "sha256": digest(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ),
        "counts": {k: len(v) for k, v in value.items()},
    }


def xml(data: bytes):
    if b"<!ENTITY" in data.upper() or re.search(rb"<!DOCTYPE[^>]*\[", data, re.I):
        raise ValueError("internal DTD/entity-bearing XML is outside this conversion profile")
    data = re.sub(rb"<!DOCTYPE[^>]*>", b"", data, flags=re.I)
    return etree.fromstring(data, PARSER)


def local_path(base: str, target: str) -> str:
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(target)))
    if path.startswith("../") or path.startswith("/") or "\\" in path:
        raise ValueError("source resource escapes package")
    return path


def node(tag: str, text: str | None = None, **attrs) -> dict:
    return {"tag": tag, "text": text, "attrs": attrs, "children": []}


def source_text(n: dict, *, notes: bool = True) -> str:
    if n["tag"] == "expan" or (not notes and n["tag"] == "note"):
        return ""
    return (n.get("text") or "") + "".join(
        source_text(c, notes=notes) + (c.get("tail") or "") for c in n.get("children", [])
    )


def tei_text(n, *, notes=True):
    """Source-display projection: expansion alternatives are never concatenated."""
    if etree.QName(n).localname == "expan" or (not notes and etree.QName(n).localname == "note"):
        return ""
    return (n.text or "") + "".join(tei_text(c, notes=notes) + (c.tail or "") for c in n)


def ledger(nodes: list[dict]) -> dict:
    """Independent source projection before serialization, including mixed-content tails."""
    result: dict[str, list[Any]] = {
        "blocks": [],
        "notes": [],
        "tables": [],
        "graphics": [],
        "abbreviations": [],
    }

    def abbreviations(n, parent=None):
        if n["tag"] == "abbr":
            expansion = (
                next(
                    (
                        c.get("text") or ""
                        for c in parent.get("children", [])
                        if c["tag"] == "expan"
                    ),
                    None,
                )
                if parent and parent["tag"] == "choice"
                else None
            )
            result["abbreviations"].append([source_text(n), expansion])
        for c in n.get("children", []):
            abbreviations(c, n)

    def visit(n, atomic=False):
        tag = n["tag"]
        if tag == "note":
            result["notes"].append(source_text(n))
            return
        if tag in ATOM and not atomic:
            result["blocks"].append([tag, source_text(n, notes=False)])
            atomic = True
        if tag == "table":
            result["tables"].append(
                [
                    [[c.get("attrs", {}), source_text(c)] for c in r["children"]]
                    for r in n["children"]
                ]
            )
        if tag == "graphic":
            result["graphics"].append(n["attrs"]["url"])
        for child in n.get("children", []):
            visit(child, atomic)

    for n in nodes:
        visit(n)
        abbreviations(n)
    return result


def tei_ledger(roots) -> dict:
    """Separate XML-side projection. No pretty-print stripping or Unicode normalization."""
    result: dict[str, list[Any]] = {
        "blocks": [],
        "notes": [],
        "tables": [],
        "graphics": [],
        "abbreviations": [],
    }

    for root in roots:
        text = root.find(f"{{{NS}}}text")
        for n in text.iter():
            tag = etree.QName(n).localname
            ancestors = [etree.QName(a).localname for a in n.iterancestors() if a is not text]
            if tag == "abbr":
                expansion = n.getparent().find(f"{{{NS}}}expan")
                result["abbreviations"].append(
                    [tei_text(n), (expansion.text or "") if expansion is not None else None]
                )
            if tag == "note" and "note" not in ancestors:
                result["notes"].append(tei_text(n))
            if "note" in ancestors:
                continue
            if tag in ATOM and not any(a in ATOM for a in ancestors):
                result["blocks"].append([tag, tei_text(n, notes=False)])
            if tag == "table":
                result["tables"].append(
                    [
                        [
                            [
                                {
                                    k: v
                                    for k, v in c.attrib.items()
                                    if k in {"rows", "cols", "role"}
                                },
                                tei_text(c),
                            ]
                            for c in r
                        ]
                        for r in n
                    ]
                )
            if tag == "graphic":
                result["graphics"].append(n.get("url").removeprefix("../"))
    return result


def assign_ids(model):
    ids = set()
    counter = 0

    def visit(n):
        nonlocal counter
        counter += 1
        n.setdefault("id", f"n{counter:05d}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", n["id"]) or n["id"] in ids:
            raise ValueError("invalid/duplicate source node ID: " + n["id"])
        ids.add(n["id"])
        for c in n.get("children", []):
            visit(c)

    for region in ("front", "body", "back"):
        for n in model.get(region, []):
            visit(n)


def split(model):
    body = model["body"]
    kind = model["work"]["kind"]
    expected = {"bible": "book", "book-of-mormon": "book", "quran": "surah"}.get(kind)
    if expected:
        if not body or any(n["tag"] != "div" or n["attrs"].get("type") != expected for n in body):
            raise ValueError("canonical collection requires top-level " + expected)
        mode = expected
    elif kind == "paper":
        mode = "whole"
    elif any(n["tag"] == "div" and n["attrs"].get("type") == "part" for n in body):
        mode = "part"
    elif any(n["tag"] == "div" and n["attrs"].get("type") == "chapter" for n in body):
        mode = "chapter"
    else:
        mode = "whole"
    if mode == "whole":
        return mode, [{r: model.get(r, []) for r in ("front", "body", "back")}]
    if any(n["tag"] != "div" for n in body):
        raise ValueError("split work requires explicit divisions for all body material")
    groups = [{"body": [n]} for n in body]
    groups[0]["front"] = model.get("front", [])
    groups[-1]["back"] = model.get("back", [])
    return mode, groups


def _emit(parent, n):
    attrs = {f"{{{XML}}}id": n["id"], **n.get("attrs", {})}
    if n["tag"] == "graphic" and attrs.get("url", "").startswith("assets/"):
        attrs["url"] = "../" + attrs["url"]
    e = etree.SubElement(parent, f"{{{NS}}}{n['tag']}", attrs)
    e.text = n.get("text")
    for child in n.get("children", []):
        _emit(e, child)
    e.tail = n.get("tail")
    return e


def header(root, work, title, source_hash):
    h = etree.SubElement(root, f"{{{NS}}}teiHeader")
    f = etree.SubElement(h, f"{{{NS}}}fileDesc")
    ts = etree.SubElement(f, f"{{{NS}}}titleStmt")
    etree.SubElement(ts, f"{{{NS}}}title").text = title
    for author in work.get("authors", []):
        etree.SubElement(ts, f"{{{NS}}}author").text = author
    ed = etree.SubElement(f, f"{{{NS}}}editionStmt")
    etree.SubElement(ed, f"{{{NS}}}edition").text = work["edition"]
    pub = etree.SubElement(f, f"{{{NS}}}publicationStmt")
    etree.SubElement(
        pub, f"{{{NS}}}p"
    ).text = "Unpublished document conversion; source rights unchanged."
    sd = etree.SubElement(f, f"{{{NS}}}sourceDesc")
    b = etree.SubElement(sd, f"{{{NS}}}bibl")
    etree.SubElement(b, f"{{{NS}}}title").text = work["title"]
    etree.SubElement(b, f"{{{NS}}}idno", type="work").text = work["id"]
    etree.SubElement(b, f"{{{NS}}}idno", type="sha256").text = source_hash
    enc = etree.SubElement(h, f"{{{NS}}}encodingDesc")
    etree.SubElement(enc, f"{{{NS}}}projectDesc").append(etree.Element(f"{{{NS}}}p"))
    enc[0][0].text = (
        PROFILE + "; logical reading text; no page/wrapped-line markup. "
        "Reading selects choice/abbr (source display); choice/expan preserves only "
        "explicit source expansion text and is excluded from reading projection."
    )
    if work.get("scheme"):
        rd = etree.SubElement(enc, f"{{{NS}}}refsDecl")
        etree.SubElement(rd, f"{{{NS}}}p").text = json.dumps(
            work["scheme"], ensure_ascii=False, sort_keys=True
        )
        etree.SubElement(rd, f"{{{NS}}}p").text = (
            "Canonical spans use empty anchors, start inclusive and end exclusive. "
            "Reading includes paragraph and poetry text/tails, excluding notes, headings "
            "and figure descriptions or expansion alternatives. Paragraph/poetry boundaries insert two LF. "
            "Numbers remain source strings; bridges and alternate numbers do not create new endpoints."
        )
    pd = etree.SubElement(h, f"{{{NS}}}profileDesc")
    lu = etree.SubElement(pd, f"{{{NS}}}langUsage")
    etree.SubElement(lu, f"{{{NS}}}language", ident=work["language"]).text = work["language"]


def convert_model(source: Path, output: Path, model: dict, assets: dict, evidence: dict):
    """Write a new directory only, validate before exposing the completed package."""
    if output.exists():
        raise ValueError("output already exists; choose a new directory")
    if "sourceText" in evidence:
        text = evidence.pop("sourceText")
        evidence["sourceTextSha256"] = digest(text.encode())
        evidence["sourceTextCharacters"] = len(text)
    model = copy.deepcopy(model)
    work = model["work"]
    for key in ("id", "title", "language", "kind", "edition"):
        if not isinstance(work.get(key), str) or not work[key]:
            raise ValueError("declared work metadata required: " + key)
    if work["kind"] not in {"book", "paper", "bible", "quran", "book-of-mormon"}:
        raise ValueError("unsupported work kind")
    if work["kind"] in {"bible", "quran", "book-of-mormon"}:
        required = {"id", "version", "segmentation", "versification"}
        if work["kind"] == "quran":
            required |= {"reading"}
        if not required <= work.get("scheme", {}).keys() or any(
            not work["scheme"][k] for k in required
        ):
            raise ValueError(
                "canonical scheme/reading/segmentation must be declared without fallback"
            )
    assign_ids(model)
    mode, groups = split(model)
    expected = ledger([n for r in ("front", "body", "back") for n in model.get(r, [])])
    roots, documents, destinations = [], [], {}
    for i, group in enumerate(groups, 1):
        name = f"documents/d{i:03d}.xml"
        root = etree.Element(
            f"{{{NS}}}TEI",
            nsmap={None: NS},
            attrib={f"{{{XML}}}id": f"d{i:03d}", f"{{{XML}}}lang": work["language"]},
        )
        nodes = [n for r in ("front", "body", "back") for n in group.get(r, [])]
        sub = group["body"][0] if mode != "whole" else None
        label = (
            next((source_text(c) for c in sub.get("children", []) if c["tag"] == "head"), sub["id"])
            if sub
            else work["title"]
        )
        header(
            root, work, work["title"] + " — " + label if sub else label, digest(source.read_bytes())
        )
        tx = etree.SubElement(root, f"{{{NS}}}text")
        for r in ("front", "body", "back"):
            if group.get(r) or r == "body":
                region = etree.SubElement(tx, f"{{{NS}}}{r}")
                region.set(f"{{{XML}}}id", f"d{i:03d}-{r}")
                for n in group.get(r, []):
                    _emit(region, n)
        for n in tx.iterdescendants():
            if etree.QName(n).localname in {"front", "body", "back"}:
                continue
            if n.get(f"{{{XML}}}id"):
                destinations[n.get(f"{{{XML}}}id")] = name
        documents.append(
            {
                "id": f"d{i:03d}",
                "path": name,
                "region": next(r for r in group if group[r]),
                "roots": [n["id"] for n in nodes],
                "title": label,
            }
        )
        roots.append(root)
    refs = []
    for root, doc in zip(roots, documents, strict=True):
        for ref in root.xpath("//t:ref", namespaces=T):
            target = ref.get("target", "")
            key = target.removeprefix("#")
            if key in destinations:
                ref.set(
                    "target",
                    ("" if destinations[key] == doc["path"] else Path(destinations[key]).name)
                    + "#"
                    + key,
                )
                ref.set("type", "resolved")
            else:
                ref.set("type", "unresolved")
            refs.append(
                {
                    "document": doc["path"],
                    "id": ref.get(f"{{{XML}}}id"),
                    "target": ref.get("target"),
                    "status": ref.get("type"),
                }
            )
    # ref status is not text/structure and is intentionally absent from the fidelity ledger.
    citations = []
    for citation in model.get("citations", []):
        start, end = citation["from"], citation["to"]
        if (
            start not in destinations
            or end not in destinations
            or destinations[start] != destinations[end]
        ):
            raise ValueError("canonical endpoints missing or span crosses standalone files")
        path = destinations[start]
        root = roots[next(i for i, d in enumerate(documents) if d["path"] == path)]
        so = root.find(f"{{{NS}}}standOff")
        if so is None:
            so = etree.SubElement(root, f"{{{NS}}}standOff")
        if len(so) == 0:
            etree.SubElement(so, f"{{{NS}}}spanGrp", type="verse")
        etree.SubElement(
            so[0],
            f"{{{NS}}}span",
            attrib={
                f"{{{XML}}}id": citation["id"],
                "n": citation["n"],
                "from": "#" + start,
                "to": "#" + end,
            },
        )
        citations.append({**citation, "document": path})
    hierarchy = {
        r: [hierarchy_node(n, destinations) for n in model.get(r, [])]
        for r in ("front", "body", "back")
    }
    index = {
        "profile": PROFILE,
        "upstream": "TEI P5 4.12.0",
        "work": work,
        "sourceSha256": digest(source.read_bytes()),
        "split": mode,
        "documents": documents,
        "readingOrder": [d["path"] for d in documents],
        "hierarchy": hierarchy,
        "references": refs,
        "citations": citations,
        "evidence": evidence,
        "assets": {p: digest(b) for p, b in assets.items()},
    }
    created = False
    try:
        output.mkdir(parents=True)
        created = True
        for root, doc in zip(roots, documents, strict=True):
            dest = output / doc["path"]
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(etree.tostring(root, encoding="utf-8", xml_declaration=True))
        for name, data in assets.items():
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        write_json(output / "index.json", index)
        write_json(output / "source-ledger.json", ledger_digest(expected))
        result = validate(output)
        write_json(output / "validation.json", result)
        return result
    except Exception:
        if created:
            shutil.rmtree(output)
        raise


def hierarchy_node(n, destinations):
    return {
        "id": n["id"],
        "tag": n["tag"],
        "n": n.get("attrs", {}).get("n"),
        "type": n.get("attrs", {}).get("type") if n["tag"] in {"div", "list"} else None,
        "document": destinations[n["id"]],
        "children": [
            hierarchy_node(c, destinations) for c in n.get("children", []) if c["tag"] == "div"
        ],
    }


def verse_text(root, start: str, end: str) -> str:
    """Half-open empty-anchor interval; p/l reading text only, excluding notes/heads.

    Source paragraph/poetry boundaries insert two LF. Inline text/tails are exact;
    no Unicode normalization or trimming is performed.
    """
    active = False
    output = []

    def visit(n, in_reading=False):
        nonlocal active
        tag = etree.QName(n).localname
        if tag in {"note", "head", "figDesc", "expan"}:
            return
        if tag == "anchor":
            ident = n.get(f"{{{XML}}}id")
            if ident == end:
                active = False
            if ident == start:
                active = True
        reading = in_reading or tag in {"p", "l"}
        if active and reading and n.text:
            output.append(n.text)
        for child in n:
            visit(child, reading)
            if active and reading and child.tail:
                output.append(child.tail)
        if active and tag in {"p", "l"}:
            output.append("\n\n")

    visit(root.find(f"{{{NS}}}text"))
    return "".join(output)


@cache
def validators():
    return (
        etree.RelaxNG(etree.parse(str(BASE / "profile/upstream/tei_all.rng"))),
        etree.RelaxNG(etree.parse(str(BASE / "profile/profile.rng"))),
        isoschematron.Schematron(etree.parse(str(BASE / "profile/profile.sch")), store_report=True),
    )


def validate(path: Path):
    index = json.loads((path / "index.json").read_text())
    if index["profile"] != PROFILE or index["upstream"] != "TEI P5 4.12.0":
        raise ValueError("unsupported profile/upstream")
    docs = index["documents"]
    if (
        not docs
        or index["readingOrder"] != [d["path"] for d in docs]
        or len(set(index["readingOrder"])) != len(docs)
    ):
        raise ValueError("wrong/duplicate reading order")
    upstream, rng, sch = validators()
    roots, by_file, ids = [], {}, {}
    for d in docs:
        if not re.fullmatch(r"documents/d[0-9]{3,}\.xml", d["path"]):
            raise ValueError("invalid document path")
        root = xml((path / d["path"]).read_bytes())
        work = index["work"]
        if root.get(f"{{{XML}}}id") != d["id"] or root.get(f"{{{XML}}}lang") != work["language"]:
            raise ValueError("document/header identity mismatch")
        if (
            root.xpath(
                "string(t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno[@type='work'])",
                namespaces=T,
            )
            != work["id"]
            or root.xpath("string(t:teiHeader/t:fileDesc/t:editionStmt/t:edition)", namespaces=T)
            != work["edition"]
        ):
            raise ValueError("work/edition header mismatch")
        if work.get("scheme"):
            declared_scheme = root.xpath(
                "string(t:teiHeader/t:encodingDesc/t:refsDecl/t:p)", namespaces=T
            )
            if json.loads(declared_scheme) != work["scheme"]:
                raise ValueError("canonical scheme/reading header mismatch")
        for schema in (upstream, rng, sch):
            if not schema.validate(root):
                raise ValueError(f"schema/semantic validation: {d['path']}: {schema.error_log}")
        roots.append(root)
        by_file[d["path"]] = root
        for n in root.xpath("t:text/*//*[@xml:id]", namespaces=T):
            ident = n.get(f"{{{XML}}}id")
            if ident in ids:
                raise ValueError("duplicate package ID")
            ids[ident] = (d["path"], n)
        rootids = [n.get(f"{{{XML}}}id") for n in root.xpath("t:text/*/*", namespaces=T)]
        if rootids != d["roots"]:
            raise ValueError("wrong document roots/splitting")
        for table in root.xpath("//t:table", namespaces=T):
            check_table(table)
        for span in root.xpath("//t:span", namespaces=T):
            anchors = root.xpath(
                "t:text//t:anchor[not(ancestor::t:note or ancestor::t:head or ancestor::t:figDesc or ancestor::t:expan)]/@xml:id",
                namespaces=T,
            )
            start, end = span.get("from")[1:], span.get("to")[1:]
            if (
                start not in anchors
                or end not in anchors
                or anchors.index(start) >= anchors.index(end)
            ):
                raise ValueError("missing/reversed canonical anchor endpoints")
    actual_paths = {p.relative_to(path).as_posix() for p in (path / "documents").glob("*.xml")}
    if actual_paths != set(index["readingOrder"]):
        raise ValueError("unindexed/missing documents")
    observed_refs, observed_citations = [], []
    for d, root in zip(docs, roots, strict=True):
        for ref in root.xpath("//t:ref", namespaces=T):
            target = ref.get("target", "")
            observed_refs.append(
                {
                    "document": d["path"],
                    "id": ref.get(f"{{{XML}}}id"),
                    "target": target,
                    "status": ref.get("type"),
                }
            )
            if ref.get("type") == "resolved":
                parts = urlsplit(target)
                dest = local_path(d["path"], parts.path) if parts.path else d["path"]
                if parts.fragment not in ids or ids[parts.fragment][0] != dest:
                    raise ValueError("missing resolved reference target")
        for span in root.xpath("//t:span", namespaces=T):
            observed_citations.append(
                (
                    d["path"],
                    span.get(f"{{{XML}}}id"),
                    span.get("n"),
                    span.get("from")[1:],
                    span.get("to")[1:],
                )
            )
    if observed_refs != index["references"]:
        raise ValueError("reference index mismatch")
    expected_citations = [
        (c["document"], c["id"], c["n"], c["from"], c["to"]) for c in index["citations"]
    ]
    if sorted(observed_citations) != sorted(expected_citations):
        raise ValueError("canonical citation index mismatch")
    flat = []

    def tree(n, parent=None):
        if n["id"] not in ids or ids[n["id"]][0] != n["document"]:
            raise ValueError("hierarchy endpoint missing")
        actual = ids[n["id"]][1]
        if (
            etree.QName(actual).localname != n["tag"]
            or (actual.get("type") if n["tag"] in {"div", "list"} else None) != n["type"]
        ):
            raise ValueError("hierarchy type mismatch")
        if actual.get("n") != n.get("n"):
            raise ValueError("hierarchy source-number mismatch")
        if parent is not None and actual.getparent() is not parent:
            raise ValueError("hierarchy parent mismatch")
        flat.append(n["id"])
        if [c.get(f"{{{XML}}}id") for c in actual if etree.QName(c).localname == "div"] != [
            c["id"] for c in n["children"]
        ]:
            raise ValueError("hierarchy child order mismatch")
        for c in n["children"]:
            tree(c, actual)

    for r in ("front", "body", "back"):
        for n in index["hierarchy"][r]:
            tree(n)
            if etree.QName(ids[n["id"]][1].getparent()).localname != r:
                raise ValueError("wrong region")
    ordered = [
        ident
        for root in roots
        for ident in root.xpath(
            "t:text/*//*[self::t:div or parent::t:front or parent::t:body or parent::t:back]/@xml:id",
            namespaces=T,
        )
    ]
    if ordered != flat:
        raise ValueError("hierarchy reading order mismatch")
    mode = index["split"]
    body = index["hierarchy"]["body"]
    expected_mode = {"bible": "book", "book-of-mormon": "book", "quran": "surah"}.get(
        index["work"]["kind"]
    )
    if expected_mode and mode != expected_mode:
        raise ValueError("wrong canonical split")
    if not expected_mode:
        kinds = {n["type"] for n in body if n["tag"] == "div"}
        derived = (
            "whole"
            if index["work"]["kind"] == "paper"
            else "part"
            if "part" in kinds
            else "chapter"
            if "chapter" in kinds
            else "whole"
        )
        if mode != derived:
            raise ValueError("wrong ordinary-work split")
    if mode != "whole":
        if any(len(root.xpath("t:text/t:body/*", namespaces=T)) != 1 for root in roots):
            raise ValueError("split document must contain one highest body division")
        for n in body:
            if n["tag"] != "div" or (expected_mode and n["type"] != expected_mode):
                raise ValueError("wrong canonical division")
        if mode == "chapter" and any(n["type"] == "part" for n in body):
            raise ValueError("parts must retain chapters")
    elif len(docs) != 1:
        raise ValueError("whole work requires one document")
    expected = json.loads((path / "source-ledger.json").read_text())
    actual = tei_ledger(roots)
    if expected != ledger_digest(actual):
        raise ValueError("independent text/note/table/asset fidelity mismatch")
    if index["evidence"].get("sourceTextSha256") is not None:
        from .sources import normalized

        def raw_output(n):
            if etree.QName(n).localname in {"figDesc", "expan"}:
                return ""
            block = etree.QName(n).localname in {
                "p",
                "head",
                "div",
                "cell",
                "item",
                "l",
                "note",
                "quote",
                "lg",
                "list",
                "table",
                "row",
            }
            text = (n.text or "") + "".join(raw_output(c) + (c.tail or "") for c in n)
            return " " + text + " " if block else text

        observed = normalized(" ".join(raw_output(root.find(f"{{{NS}}}text")) for root in roots))
        if digest(observed.encode()) != index["evidence"]["sourceTextSha256"]:
            raise ValueError(
                f"whole-source text hash mismatch: output={len(observed)} characters; source={index['evidence']['sourceTextCharacters']} characters"
            )
    for p, sha in index["assets"].items():
        if (
            not p.startswith("assets/")
            or local_path("index.json", p) != p
            or digest((path / p).read_bytes()) != sha
        ):
            raise ValueError("asset path/hash mismatch")
    for graphic in actual["graphics"]:
        if graphic not in index["assets"]:
            raise ValueError("graphic asset missing")
    evidence = index["evidence"]
    if "sourceAbbreviationsSha256" in evidence:
        from .sources import normalized

        pairs = [[normalized(a), expansion] for a, expansion in actual["abbreviations"]]
        if (
            digest(json.dumps(pairs, ensure_ascii=False).encode())
            != evidence["sourceAbbreviationsSha256"]
            or len(pairs) != evidence["sourceAbbreviationCount"]
        ):
            raise ValueError("original-source abbreviation/expansion coverage mismatch")
    if "sourceNoteHashes" in evidence:
        from .sources import normalized

        observed_notes = [
            digest(normalized(raw_output(n)).encode())
            for root in roots
            for n in root.xpath("t:text//t:note[not(ancestor::t:note)]", namespaces=T)
        ]
        observed_graphics = [index["assets"][g] for g in actual["graphics"]]
        observed_alts = [
            "".join(n.itertext())
            for root in roots
            for n in root.xpath("t:text//t:figDesc", namespaces=T)
        ]
        if (
            observed_notes != evidence["sourceNoteHashes"]
            or len(actual["tables"]) != evidence["sourceTableCount"]
        ):
            raise ValueError("original-source note/table coverage mismatch")
        if (
            observed_graphics != evidence["sourceGraphicHashes"]
            or observed_alts != evidence["sourceAltText"]
            or sorted(set(index["assets"].values())) != evidence["sourceAssetHashes"]
        ):
            raise ValueError("original-source graphic/alt/asset coverage mismatch")
    return {
        "valid": True,
        "documents": len(docs),
        "blocks": len(actual["blocks"]),
        "notes": len(actual["notes"]),
        "tables": len(actual["tables"]),
        "assets": len(index["assets"]),
        "citations": len(expected_citations),
        "unresolvedReferences": sum(r["status"] == "unresolved" for r in observed_refs),
        "checks": [
            "upstream P5",
            "profile RNG",
            "Schematron",
            "package hierarchy/order/links",
            "source ledger exact Unicode/text/tails/notes/tables",
            "original-source text and semantic coverage"
            if "sourceTextSha256" in evidence
            else "declared authored source projection",
            "asset hashes",
        ],
    }


def check_table(table):
    occupied = set()
    widths = []
    for rownum, row in enumerate(table):
        col = 0
        for cell in row:
            while (rownum, col) in occupied:
                col += 1
            rows, cols = int(cell.get("rows", "1")), int(cell.get("cols", "1"))
            if rows <= 0 or cols <= 0 or rownum + rows > len(table):
                raise ValueError("invalid table span")
            for r in range(rownum, rownum + rows):
                for c in range(col, col + cols):
                    if (r, c) in occupied:
                        raise ValueError("overlapping table span")
                    occupied.add((r, c))
            col += cols
        widths.append(max((c + 1 for r, c in occupied if r == rownum), default=0))
    if not widths or len(set(widths)) != 1 or len(occupied) != sum(widths):
        raise ValueError("ragged/incomplete table grid")
