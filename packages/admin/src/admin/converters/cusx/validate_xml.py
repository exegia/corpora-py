"""Reference checks for the unpublished Corpora USX Extension draft.

Grammar validity is separate from profile, range and collection conformance.
This is a draft checker, not an importer or a text-authenticity verifier.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lxml import etree

HERE = Path(__file__).resolve().parent
DRAFT = HERE / "draft" if (HERE / "draft").exists() else HERE
NS = "urn:corpora:usx-extension:0.1"
Q = "{" + NS + "}"
QURAN_UNITS = {"juz", "hizb", "rub", "manzil", "ruku"}


class InvalidDocumentError(ValueError):
    pass


def require(condition, code, explanation):
    if not condition:
        raise InvalidDocumentError(f"{code}: {explanation}")


def parser():
    return etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)


def verify_upstream():
    lock = json.loads((DRAFT / "schema/upstream/source-lock.json").read_text())
    for name, source in lock["files"].items():
        actual = hashlib.sha256((DRAFT / "schema/upstream" / name).read_bytes()).hexdigest()
        require(actual == source["sha256"], "BASE-001", f"Pinned USX source changed: {name}")


def grammar():
    verify_upstream()
    return etree.RelaxNG(etree.parse(str(DRAFT / "schema/corpora.rng"), parser()))


def load(path):
    try:
        tree = etree.parse(str(path), parser())
    except etree.XMLSyntaxError as error:
        raise InvalidDocumentError(f"XML-001: {error}") from error
    require(not tree.docinfo.doctype, "XML-002", "DOCTYPE is outside this draft contract")
    return tree


def check_document(root):
    require(
        root.find(Q + "title").text and root.find(Q + "title").text.strip(),
        "DOC-001",
        "Document title must not be blank",
    )
    for meta in root.findall(Q + "metadata/" + Q + "meta"):
        name = meta.get("name", "").lower()
        require(
            not any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in ("source", "conversion", "parser", "tf")
            ),
            "PROV-001",
            "Conversion evidence belongs outside content XML",
        )
    profile = root.get("profile", "general")
    require(
        profile in {"general", "bible", "quran", "book-of-mormon", "custom"},
        "PRO-001",
        "Unknown profile requires a specification and checker extension",
    )
    if profile in {"bible", "quran", "book-of-mormon"}:
        require(
            root.get("type") == "scripture", "PRO-002", "Scripture profiles require type=scripture"
        )
    if root.get("type") == "scripture" or any(root.iter("verse")):
        require(
            root.get("numbering"),
            "PRO-003",
            "Scripture and verse-bearing documents require an explicit numbering scheme",
        )
    if profile == "quran":
        require(
            root.get("reading") and root.get("edition"),
            "QUR-001",
            "Quran profile requires reading and edition",
        )
    identities = set()
    open_ranges = {}
    used_starts = set()
    marks = set()
    fragments = []
    chapter = None
    verse = None
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        for attribute in element.attrib:
            name = etree.QName(attribute).localname.lower()
            require(
                name not in {"srcloc", "sourcepath", "sourceformat", "tfnode"}
                and not name.startswith(
                    tuple(
                        prefix + separator
                        for prefix in ("source", "conversion", "parser", "tf")
                        for separator in (".", "_", "-")
                    )
                ),
                "PROV-001",
                "Import attributes belong in conversion metadata, not content",
            )
        for name in ["sid", "eid", "vid", "loc", "number", "altnumber"]:
            if name in element.attrib:
                require(element.get(name).strip(), "ADR-001", f"{name} must not be blank")
        node_id = element.get(Q + "id") or element.get("link-id")
        if node_id:
            require(
                node_id not in identities,
                "ADR-002",
                "Content anchor IDs must be unique in a document",
            )
            identities.add(node_id)
        is_boundary = element.tag == Q + "boundary"
        if (
            element.tag not in {"chapter", "verse"}
            and not is_boundary
            and element.tag != Q + "mark"
        ):
            continue
        require(
            not any(a.tag in {"note", "sidebar"} for a in element.iterancestors()),
            "RNG-001",
            "Main-text ranges and Quran marks cannot be placed inside notes or sidebars",
        )
        if element.tag == Q + "mark":
            require(profile == "quran", "QUR-002", "Quran marks require the Quran profile")
            key = (element.get("scheme"), element.get("id"))
            require(key not in marks, "MRK-001", "Mark IDs are unique within a scheme and document")
            marks.add(key)
            continue
        if is_boundary:
            unit, scheme = element.get("unit"), element.get("scheme")
            require(
                unit not in QURAN_UNITS or profile == "quran",
                "QUR-002",
                "Quran divisions require the Quran profile",
            )
            require(
                not scheme.lower().startswith(("epub", "xhtml", "pdf", "scan", "printed")),
                "SCHM-001",
                "Range schemes identify content structure, not an import layout",
            )
            axis = (unit, scheme)
        else:
            axis = (element.tag, root.get("numbering", "local"))
        sid, eid = element.get("sid"), element.get("eid")
        if sid:
            require(axis not in open_ranges, "RNG-002", "A range cannot reopen its active axis")
            key = (*axis, sid)
            require(
                key not in used_starts, "RNG-003", "A range start ID cannot repeat on the same axis"
            )
            used_starts.add(key)
            if element.tag == "chapter":
                require(verse is None, "SCR-001", "Close the verse before opening a chapter")
                chapter = sid
            elif element.tag == "verse":
                require(chapter is not None, "SCR-002", "A verse requires an open chapter")
                verse = sid
            open_ranges[axis] = sid
            if is_boundary:
                fragments.append((axis, sid, element.get("fragment", "whole")))
        else:
            require(
                open_ranges.get(axis) == eid,
                "RNG-004",
                "End must match the active start on its axis",
            )
            if element.tag == "chapter":
                require(verse is None, "SCR-003", "Close the verse before closing its chapter")
                chapter = None
            elif element.tag == "verse":
                verse = None
            del open_ranges[axis]
    require(
        not open_ranges,
        "RNG-005",
        "All ranges must close within their document, including clipped fragments",
    )
    return fragments


def validate(path, schema=None, check_targets=True):
    path = Path(path).resolve()
    schema = schema if schema is not None else grammar()
    tree = load(path)
    require(schema.validate(tree), "SCH-001", str(schema.error_log.last_error))
    root = tree.getroot()
    if root.tag == Q + "document":
        return check_document(root)
    require(
        root.find(Q + "title").text and root.find(Q + "title").text.strip(),
        "COL-001",
        "Collection title must not be blank",
    )
    require(
        root.get("profile", "general") in {"general", "bible", "quran", "book-of-mormon", "custom"},
        "PRO-001",
        "Unknown collection profile requires a specification and checker extension",
    )
    membership_ids = set()
    identities = {}
    fragment_sequences = {}
    for element in root.iter():
        if element.tag not in {Q + "item", Q + "group"}:
            continue
        identity = element.get("id")
        require(
            identity not in membership_ids,
            "COL-002",
            "Item and group IDs must be unique throughout the collection",
        )
        membership_ids.add(identity)
        if element.tag == Q + "group":
            continue
        parts = urlsplit(element.get("href"))
        require(
            not parts.scheme and not parts.netloc and not parts.query and not parts.fragment,
            "COL-003",
            "Item href is a local relative XML path without URI components",
        )
        target = (path.parent / unquote(parts.path)).resolve()
        require(
            bool(parts.path)
            and not parts.path.startswith("/")
            and target.is_relative_to(path.parent),
            "COL-003",
            "Item path must stay within the collection directory",
        )
        if not check_targets:
            continue
        require(target.is_file(), "COL-004", f"Missing collection target: {element.get('href')}")
        target_tree = load(target)
        require(schema.validate(target_tree), "SCH-001", str(schema.error_log.last_error))
        document = target_tree.getroot()
        require(
            document.tag == Q + "document",
            "COL-005",
            "Items reference documents; groups express nesting",
        )
        document_id = document.get("id")
        require(
            document_id not in identities or identities[document_id] == target,
            "COL-006",
            "Different target files cannot claim the same document identity",
        )
        identities[document_id] = target
        profile = root.get("profile", "general")
        if root.get("kind") == "canon" and profile in {"bible", "quran", "book-of-mormon"}:
            require(
                document.get("profile") == profile,
                "COL-007",
                "Canon target profile must match its declared profile",
            )
        for axis, sid, fragment in check_document(document):
            scope = (document.get("edition", ""), document.get("reading", ""), *axis, sid)
            fragment_sequences.setdefault(scope, []).append(fragment)
    for sequence in fragment_sequences.values():
        if sequence == ["whole"] or all(f == "whole" for f in sequence):
            continue
        require(
            len(sequence) >= 2
            and sequence[0] == "start"
            and sequence[-1] == "end"
            and all(f == "middle" for f in sequence[1:-1]),
            "COL-008",
            "A clipped range in a complete collection requires start, optional middle fragments, then end",
        )
    return []


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("paths", nargs="+", type=Path)
    cli.add_argument(
        "--shape-only", action="store_true", help="Check grammar only, without semantics or targets"
    )
    args = cli.parse_args()
    schema = grammar()
    for path in args.paths:
        if args.shape_only:
            tree = load(path)
            require(schema.validate(tree), "SCH-001", str(schema.error_log.last_error))
        else:
            validate(path, schema)
        print(f"PASS: {path.name}")
