"""Bounded, read-only source extraction experiments; private outputs stay outside specs.

This is an experiment harness, not the application's production adapter registry.
Extractors produce source evidence; one format-independent mapper emits the contract.
"""

import argparse
import hashlib
import importlib.util
import json
import posixpath
import re
import shutil
import stat
import sys
import tempfile
import types
import zipfile
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path, PurePosixPath

from lxml import etree
from pypdf import PdfReader
from pypdf.errors import EmptyFileError, PdfReadError
from tf.fabric import Fabric

REPO = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO / "specs/corpus-document/v0.4.0"
CHECKER_SPEC = importlib.util.spec_from_file_location(
    "checker", REPO / "scripts/check_corpus_document.py"
)
checker = importlib.util.module_from_spec(CHECKER_SPEC)
CHECKER_SPEC.loader.exec_module(checker)
GATE_SPEC = importlib.util.spec_from_file_location("pdf_gate", SPEC_ROOT / "pdf_acceptance.py")
pdf_gate = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(pdf_gate)


@dataclass
class Extraction:
    sample: str
    text: str
    blocks: list = field(default_factory=list)
    losses: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    assets: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    decision: dict | None = None

    def block(self, kind, start, end, evidence, source_id=None, attrs=None):
        self.blocks.append(
            {
                "kind": kind,
                "start": start,
                "end": end,
                "evidence": evidence,
                "sourceId": source_id,
                "attributes": attrs or {},
            }
        )
        return len(self.blocks) - 1


def digest(data):
    return hashlib.sha256(data).hexdigest()


def asset(path, media_type):
    data = path.read_bytes()
    return {
        "name": path.name,
        "mediaType": media_type,
        "sha256": digest(data),
        "bytes": len(data),
        "mtimeNs": path.stat().st_mtime_ns,
    }


def blank_blocks(text, start=0):
    cursor = 0
    for delimiter in re.finditer(r"\n[ \t]*\n+", text):
        if text[cursor : delimiter.start()].strip():
            yield start + cursor, start + delimiter.start()
        cursor = delimiter.end()
    if text[cursor:].strip():
        yield start + cursor, start + len(text)


def existing_plain_parser(path):
    """Load only the existing plain parser, without importing the application package."""
    package = types.ModuleType("experiment_parsers")
    package.__path__ = [str(REPO / "packages/admin/src/admin/parsers")]
    sys.modules[package.__name__] = package
    for name in ("schema", "_plain"):
        spec = importlib.util.spec_from_file_location(
            f"experiment_parsers.{name}", Path(package.__path__[0]) / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return list(sys.modules["experiment_parsers._plain"].PlainTextParser().iter_units(str(path)))


def extract_plain(path):
    data = path.read_bytes()
    text = data.decode("utf-8")  # preserve CR/LF; no Path.read_text newline conversion
    result = Extraction("plain-single-document", text)
    result.assets = [asset(path, "text/plain")]
    for start, end in blank_blocks(text):
        result.block("core:paragraph", start, end, "inferred: blank-line delimiter")
    baseline = existing_plain_parser(path)
    reconstructed = "\n\n".join("".join(t.text + t.after for t in unit.tokens) for unit in baseline)
    result.metrics = {
        "utf8ByteRoundTrip": text.encode("utf-8") == data,
        "existingParserReconstructionEqual": reconstructed == text,
        "existingParserScalarDelta": len(text) - len(reconstructed),
        "existingParserNonWhitespaceEqual": "".join(text.split()) == "".join(reconstructed.split()),
        "paragraphsAreInferred": True,
        "sourceEncoding": "UTF-8",
        "sourceFormatVersion": "not applicable to plain text",
    }
    result.losses = [
        "Paragraph boundaries are a blank-line heuristic, not explicit authored structure.",
        "No chapter, author or language metadata was inferred from document contents.",
    ]
    return result


def extract_pdf(path, sample):
    try:
        reader = PdfReader(path)
        selected_pages = list(reader.pages)[:3]
        pages = [(page.extract_text() or "") for page in selected_pages]
    except (PdfReadError, EmptyFileError):
        result = Extraction(sample, "")
        result.assets = [asset(path, "application/pdf")]
        result.losses = [
            "PDF parsing/extraction failed; recovered fragments cannot be accepted as a partial document."
        ]
        result.metrics = {"parserFailure": True, "sourcePages": 0, "ocrPerformed": False}
        result.decision = pdf_gate.decide(
            result.assets[0]["sha256"], 0, "bounded-sample", [], extraction_failed=True
        )
        return result
    result = Extraction(sample, "\n".join(pages))
    result.assets = [asset(path, "application/pdf")]
    offset = 0
    page_spans = []
    for index, text in enumerate(pages):
        page_spans.append((offset, offset + len(text)))
        assert result.text[offset : offset + len(text)] == text
        block = result.block(
            "core:page", offset, offset + len(text), "explicit: PDF page sequence", str(index)
        )
        result.citations.append((f"page-{index + 1}", block))
        for start, end in blank_blocks(text, offset):
            result.block(
                "experiment:paragraphCandidate",
                start,
                end,
                "inferred: extraction blank-line block; uncertain reading order",
            )
        offset += len(text) + 1
    if len(pages) > 1 and pages[0] and pages[1]:
        # Deliberately an uncertain overlap candidate, never asserted as an authored paragraph.
        start = max(page_spans[0][0], page_spans[0][1] - 120)
        end = min(page_spans[1][1], page_spans[1][0] + 120)
        result.block(
            "experiment:paragraphCandidate",
            start,
            end,
            "hypothesis: page-boundary window, not recognized paragraph",
        )
    result.metrics = {
        "sourcePages": len(reader.pages),
        "sourceFormatVersion": path.read_bytes().splitlines()[0].decode("ascii", errors="replace"),
        "selectedPageIndices": list(range(len(pages))),
        "pageScalars": [len(t) for t in pages],
        "emptyExtractedPages": sum(not t for t in pages),
        "textMatchesExtractor": all(
            result.text[start:end] == text
            for (start, end), text in zip(page_spans, pages, strict=True)
        ),
        "imageObjectsPerSelectedPage": [
            sum(
                obj.get_object().get("/Subtype") == "/Image"
                for obj in (page.get("/Resources", {}).get("/XObject", {}) or {}).values()
            )
            for page in selected_pages
        ],
        "textExtractionOutcome": "text-extracted"
        if any(pages)
        else "no-text-extracted; OCR needed or content unavailable",
        "hasExplicitPagination": True,
        "paragraphsAreInferred": True,
        "ocrPerformed": False,
    }
    result.losses = [
        "PDF extraction order is not independently verified against rendered page layout.",
        "Inserted one newline between selected pages; extraction whitespace is otherwise preserved.",
        "No OCR, font-position reconstruction, image capture or physical bounding boxes.",
        "Cross-page window is a labeled hypothesis, not evidence of an authored paragraph.",
        "Only first three source pages selected; empty text is not proof the page has no content.",
    ]
    assessments = [
        {
            "pageIndex": i,
            "content": "unverified" if text.strip() else "unreadable",
            "readingOrder": "unverified",
            "evidence": ["Text extractor produced content; source fidelity not visually verified"]
            if text.strip()
            else ["No extracted text and no confirmed blank-page evidence; OCR not performed"],
        }
        for i, text in enumerate(pages)
    ]
    result.decision = pdf_gate.decide(
        result.assets[0]["sha256"], len(reader.pages), "bounded-sample", assessments
    )
    return result


def walk_xml(element, result, policy="all"):
    """Record exact parser text/tails and element spans under an explicit reading policy."""
    chunks = []
    length = 0

    def append(text):
        nonlocal length
        if text:
            chunks.append(text)
            length += len(text)

    def visit(node):
        if not isinstance(node.tag, str):
            return
        tag = etree.QName(node).localname
        start = length
        if policy == "tei-first-reading" and tag == "note":
            body = "".join(node.itertext())
            block = result.block(
                "core:milestone",
                start,
                start,
                "explicit: TEI note insertion point",
                node.get("id"),
                dict(node.attrib),
            )
            result.notes.append({"block": block, "type": "experiment:note", "body": body})
            return
        if policy == "tei-first-reading" and tag == "app":
            readings = [
                n for n in node if isinstance(n.tag, str) and etree.QName(n).localname == "rdg"
            ]
            if readings:
                visit(readings[0])
                block = result.block(
                    "experiment:apparatus",
                    start,
                    length,
                    "explicit apparatus; chosen first reading",
                    node.get("id"),
                    dict(node.attrib),
                )
                alternatives = ["".join(n.itertext()) for n in readings[1:]]
                result.notes.extend(
                    {"block": block, "type": "experiment:alternativeReading", "body": body}
                    for body in alternatives
                    if body
                )
                return
        append(node.text)
        for child in node:
            visit(child)
            append(child.tail)
        end = length
        kind = None
        if tag == "w":
            kind = "core:word"
        elif tag in ("p",):
            kind = "core:paragraph"
        elif re.fullmatch(r"h[1-6]", tag):
            kind = "core:heading"
        elif tag in ("lb", "pb"):
            kind = "core:milestone"
        elif tag in ("supplied", "hi", "a"):
            kind = "experiment:span"
        if kind:
            result.block(
                kind,
                start,
                end,
                f"explicit source element: {tag}",
                node.get("id") or node.get("{http://www.w3.org/XML/1998/namespace}id"),
                dict(node.attrib),
            )

    visit(element)
    return "".join(chunks)


def extract_epub(path):
    result = Extraction("epub-spine-prose", "")
    result.assets = [asset(path, "application/epub+zip")]
    ns = {"o": "http://www.idpf.org/2007/opf"}
    with zipfile.ZipFile(path) as archive:
        container = etree.fromstring(archive.read("META-INF/container.xml"))
        opf_path = container.xpath("//*[local-name()='rootfile']/@full-path")[0]
        opf = etree.fromstring(archive.read(opf_path))
        manifest = {item.get("id"): item for item in opf.findall(".//o:manifest/o:item", ns)}
        spine = [
            r.get("idref")
            for r in opf.findall(".//o:spine/o:itemref", ns)
            if r.get("linear", "yes") != "no"
        ]
        selected = []
        for identity in spine:
            item = manifest[identity]
            if item.get("media-type") != "application/xhtml+xml":
                continue
            member = posixpath.normpath(
                posixpath.join(posixpath.dirname(opf_path), item.get("href"))
            )
            body_doc = etree.fromstring(
                archive.read(member),
                parser=etree.XMLParser(resolve_entities=False, no_network=True),
            )
            bodies = body_doc.xpath("//*[local-name()='body']")
            if not bodies:
                continue
            local = Extraction("epub-member", "")
            text = walk_xml(bodies[0], local)
            if not text.strip():
                continue
            start = len(result.text)
            if selected:
                result.text += "\n"
                start += 1
            result.text += text
            result.block(
                "experiment:spineDocument",
                start,
                start + len(text),
                "explicit: OPF linear spine",
                identity,
                {"member": member},
            )
            for block in local.blocks:
                block["start"] += start
                block["end"] += start
                block["attributes"]["member"] = member
                result.blocks.append(block)
            selected.append(member)
            if len(selected) == 3:
                break
        result.metrics = {
            "sourceFormatVersion": opf.get("version"),
            "spineItems": len(spine),
            "selectedMembers": selected,
            "spineOrderUsed": True,
            "explicitParagraphs": sum(b["kind"] == "core:paragraph" for b in result.blocks),
            "linksRetained": sum("href" in b["attributes"] for b in result.blocks),
            "originalSpineDiffersFromManifestOrder": spine
            != [key for key in manifest if key in spine],
        }
    result.losses = [
        "First three nonempty linear spine documents selected, not entire EPUB.",
        "XML parser text/tails retained; entity decoding is not source-byte preservation.",
        "Inserted newline between selected spine documents; CSS/layout/media omitted.",
        "Source href/IDs retained; links are not automatically resolved or fetched.",
        "Nested text is stored once; source style rendering and complex note semantics are unverified.",
    ]
    return result


def extract_tei(path):
    tree = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))
    element = tree.xpath("//*[local-name()='ab' and @id='V-B1K22V1-01-GEN']")[0]
    result = Extraction("tei-apparatus-block", "")
    result.assets = [asset(path, "application/xml")]
    result.text = walk_xml(element, result, "tei-first-reading")
    result.block(
        "experiment:transcriptionBlock",
        0,
        len(result.text),
        "explicit source ab; partial edition",
        element.get("id"),
        dict(element.attrib),
    )
    page_context = element.xpath("preceding::*[local-name()='pb'][1]")
    result.metrics = {
        "rootName": tree.getroot().tag,
        "sourceSchemaHint": tree.getroot().get(
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"
        ),
        "sourceFormatVersion": "unverified TEI-like source; filename version is not a schema version",
        "selector": "ab[@id='V-B1K22V1-01-GEN']",
        "sourceReadingCount": len(element.xpath(".//*[local-name()='rdg']")),
        "selectedReadingPolicy": "first rdg in each app; not a scholarly preference",
        "outsideSubtreePageContextPresent": bool(page_context),
        "selectedWords": sum(b["kind"] == "core:word" for b in result.blocks),
        "alternativeReadingsStoredSeparately": sum(
            n["type"] == "experiment:alternativeReading" for n in result.notes
        ),
    }
    result.losses = [
        "Source root is unnamespaced TEI despite namespace hints; no upstream TEI conformance claim.",
        "First-reading selection is an explicit experiment policy, not reconstructed manuscript truth.",
        "Supplied/highlight text and parser whitespace retained; lb/pb do not invent text newlines.",
        "Only one ab selected; outer page context detected but full physical page spans not reconstructed.",
        "Rejected readings stored as annotations; other apparatus metadata remains opaque source attributes.",
    ]
    return result


def extract_tf(path):
    assets = [asset(p, "text/plain") for p in sorted(path.glob("*.tf"))]
    # Text-Fabric may build caches; copy into a private temporary directory first.
    with tempfile.TemporaryDirectory(prefix="corpora-tf-experiment-") as temp:
        for source in path.glob("*.tf"):
            shutil.copyfile(source, Path(temp) / source.name)
        api = Fabric(locations=temp, modules=[""], silent="deep").load(
            "word trailer book chapter verse", silent="deep"
        )
        if not api:
            raise ValueError("Text-Fabric could not load selected source")
        verse = 428562
        slots = api.E.oslots.s(verse)
        result = Extraction("text-fabric-first-verse", "")
        result.assets = assets
        for slot in slots:
            word = api.F.word.v(slot) or ""
            trailer = api.F.trailer.v(slot) or ""
            start = len(result.text)
            result.text += word + trailer
            result.block("core:word", start, start + len(word), "explicit: TF word slot", str(slot))
        book = api.L.u(verse, otype="book")[0]
        chapter = api.L.u(verse, otype="chapter")[0]
        block = result.block(
            "core:verse", 0, len(result.text), "explicit: TF oslots; partial edition", str(verse)
        )
        result.citations = [
            (f"{api.F.book.v(book)} {api.F.chapter.v(chapter)}:{api.F.verse.v(verse)}", block)
        ]
        source_nodes = [
            node for kind in ("book", "chapter", "verse") for node in api.F.otype.s(kind)
        ]
        discontinuous = sum(
            any(b != a + 1 for a, b in zip(coverage, coverage[1:], strict=False))
            for coverage in (api.E.oslots.s(node) for node in source_nodes)
        )
        result.metrics = {
            "selectedVerseNode": verse,
            "selectedSlots": list(slots),
            "section": list(api.T.sectionFromNode(verse)),
            "sourceDisplayTemplate": "{word}{trailer}",
            "slotTextConcatenationExact": True,
            "sourceNodesCheckedForDiscontinuity": len(source_nodes),
            "discontinuousNodes": discontinuous,
            "cachesWrittenToOriginal": False,
        }
    result.losses = [
        "Only first verse and its word slots selected; no complete book/chapter claimed.",
        "Display uses explicit word+trailer features; alternate transliteration/features omitted.",
        "Local dataset has no discontinuous nodes; real discontinuity remains unverified.",
        "Local data is used privately; redistribution rights have not been established.",
    ]
    return result


def check_zip_members(archive):
    names = set()
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            raise ValueError("Unsafe archive member path")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError("Archive symlinks are not supported")
        if info.filename in names:
            raise ValueError("Duplicate archive member")
        names.add(info.filename)


def extract_usx_zip(path, sample):
    """One explicitly closed Luke chapter; private source bytes never enter specs."""
    result = Extraction(sample, "")
    result.assets = [asset(path, "application/zip")]
    with zipfile.ZipFile(path) as archive:
        check_zip_members(archive)
        candidates = [n for n in archive.namelist() if n.endswith("/LUK.usx")]
        if len(candidates) != 1:
            raise ValueError("Experiment requires one unambiguous LUK.usx member")
        member = candidates[0]
        if archive.getinfo(member).file_size > 16 * 1024 * 1024:
            raise ValueError("Selected member exceeds bounded experiment size")
        raw = archive.read(member)
        inventory = {
            name: 0 for name in ("ref", "ms", "table", "sidebar", "periph", "crossReferenceNotes")
        }
        versions = set()
        for info in archive.infolist():
            if not info.filename.lower().endswith(".usx"):
                continue
            if info.file_size > 16 * 1024 * 1024:
                raise ValueError("Archive metadata scan exceeds bounded member size")
            data = archive.read(info)
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise ValueError("DTD/entities outside supported metadata scan")
            source = etree.fromstring(
                data, etree.XMLParser(resolve_entities=False, no_network=True)
            )
            versions.add(source.get("version"))
            for element in source.iter():
                if element.tag in inventory:
                    inventory[element.tag] += 1
                if element.tag == "note" and element.get("style") == "x":
                    inventory["crossReferenceNotes"] += 1
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entities outside this experiment's supported source subset")
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    if root.tag != "usx" or root.get("version") != "3.0":
        raise ValueError("Experiment supports the observed USX 3.0 source envelope only")
    selected = []
    active = False
    for child in root:
        if child.tag == "chapter" and child.get("sid"):
            if active:
                break
            if child.get("number") == "1":
                active = True
        if active:
            selected.append(child)
    starts = {}
    matched = []
    unknown = {}
    note_refs = 0
    text = []
    length = 0

    def append(value):
        nonlocal length
        if value:
            text.append(value)
            length += len(value)

    def note_body(node):
        chunks = []
        marks = []
        attributes = []
        refs = []
        size = 0

        def add(value):
            nonlocal size
            if value:
                chunks.append(value)
                size += len(value)

        def walk(value):
            start = size
            add(value.text)
            for child in value:
                if isinstance(child.tag, str):
                    walk(child)
                add(child.tail)
            if value.tag == "char" and start < size:
                style = value.get("style", "unknown")
                marker = (
                    "usx:" + style
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", style)
                    else "experiment:sourceStyle"
                )
                marks.append({"start": start, "end": size, "type": marker})
                attributes.append(dict(value.attrib))
            if value.tag == "ref":
                refs.append(dict(value.attrib))

        walk(node)
        return "".join(chunks), marks, attributes, refs

    def visit(node):
        nonlocal note_refs
        if not isinstance(node.tag, str):
            return
        tag = node.tag
        start = length
        attributes = dict(node.attrib)
        if tag in ("chapter", "verse"):
            sid, eid = node.get("sid"), node.get("eid")
            if sid:
                if (tag, sid) in starts:
                    raise ValueError("Duplicate source milestone start")
                starts[(tag, sid)] = (length, attributes)
            elif eid:
                if (tag, eid) not in starts:
                    raise ValueError("Unmatched source milestone end")
                begin, attrs = starts.pop((tag, eid))
                attrs["eid"] = eid
                kind = "core:verse" if tag == "verse" else "usx:chapter"
                block = result.block(
                    kind,
                    begin,
                    length,
                    "explicit paired USX milestones; selected chapter scope",
                    eid,
                    attrs,
                )
                if tag == "verse":
                    result.citations.append((eid, block))
                matched.append((tag, eid))
            else:
                raise ValueError("Missing milestone identifier in selected source")
            return
        if tag == "note":
            block = result.block(
                "core:milestone", length, length, "explicit: USX note insertion", attrs=attributes
            )
            body, marks, mark_attrs, refs = note_body(node)
            note_refs += len(refs)
            if body:
                result.notes.append(
                    {
                        "block": block,
                        "type": "usx:crossReference"
                        if node.get("style") == "x"
                        else "usx:footnote",
                        "body": body,
                        "marks": marks,
                        "attributes": attributes,
                        "markAttributes": mark_attrs,
                        "references": refs,
                    }
                )
            return
        if tag == "ms":
            # None occur in the selected real chapters. Preserve any encountered point without claiming pairing.
            result.block(
                "core:milestone",
                length,
                length,
                "explicit USX ms; span semantics unimplemented",
                attrs=attributes,
            )
            unknown[tag] = unknown.get(tag, 0) + 1
            return
        append(node.text)
        for child in node:
            visit(child)
            append(child.tail)
        if tag == "para":
            kind = "usx:poetryLine" if node.get("style", "").startswith("q") else "core:paragraph"
            result.block(kind, start, length, "explicit: USX paragraph/style", attrs=attributes)
        elif tag in ("char", "ref"):
            result.block(
                "experiment:span", start, length, "explicit: USX inline element", attrs=attributes
            )
        else:
            unknown[tag] = unknown.get(tag, 0) + 1

    paragraph_count = 0
    for child in selected:
        if child.tag == "para":
            if paragraph_count:
                append("\n")
            paragraph_count += 1
        visit(child)
        # Root-level indentation/tails are not treated as reading text.
    if starts:
        raise ValueError("Selected scope contains unclosed source milestone pairs")
    if not result.citations or not any(tag == "chapter" for tag, _ in matched):
        raise ValueError("No complete chapter/verse mapping in selected scope")
    result.text = "".join(text)
    result.metrics = {
        "sourceFormatVersion": root.get("version"),
        "archiveDeclaredVersions": sorted(versions),
        "archiveStructuralInventory": inventory,
        "archiveUsxMembers": sum(n.lower().endswith(".usx") for n in archive.namelist()),
        "member": member,
        "memberSha256": digest(raw),
        "memberBytes": len(raw),
        "bookCode": root.find("book").get("code"),
        "selectedChapter": "1",
        "pairedChapters": sum(tag == "chapter" for tag, _ in matched),
        "pairedVerses": len(result.citations),
        "explicitParagraphs": paragraph_count,
        "poetryLines": sum(b["kind"] == "usx:poetryLine" for b in result.blocks),
        "notes": len(result.notes),
        "crossReferenceNotes": sum(n["type"] == "usx:crossReference" for n in result.notes),
        "structuredNoteReferences": note_refs,
        "unmappedElementCounts": unknown,
        "versesCrossingLayoutBlocks": sum(
            sum(
                p["start"] < v["end"] and v["start"] < p["end"]
                for p in result.blocks
                if p["kind"] in ("core:paragraph", "usx:poetryLine")
            )
            > 1
            for v in result.blocks
            if v["kind"] == "core:verse"
        ),
        "upstreamUsxSchemaValidated": False,
        "wholeDocumentAcceptanceAssessed": False,
    }
    result.losses = [
        "Only Luke chapter 1 selected from one member of the private archive, not whole-book or whole-archive coverage.",
        "Inserted newline between paragraphs; root formatting indentation excluded; within-paragraph text/tails retained.",
        "XML decoding normalizes source line endings and expands ordinary character entities; original source bytes are not reconstructed.",
        "Note bodies excluded from reading text and stored with styles/attributes; original metadata/authorship not reconciled.",
        "Milestone pairs checked in selected scope; upstream USX source conformance and general export are not proved.",
        "No cross-reference targets or additional ms quotation spans occur in this selection; no target resolution is invented.",
    ]
    return result


def map_to_corpora(extraction):
    """The mapper knows evidence blocks, not PDF/EPUB/TEI/TF APIs."""
    stem = extraction.sample

    def identity(name):
        return f"urn:corpora-experiment:{stem}:{name}"

    revision = identity("revision")
    stream = identity("stream")
    agent = identity("agent")
    document = {
        "specVersion": "0.4.0",
        "id": identity("bundle"),
        "requiredCapabilities": ["core:text", "core:anchors", "core:structures", "core:positions"],
        "works": [{"id": identity("work"), "title": stem}],
        "editions": [
            {
                "id": identity("edition"),
                "workId": identity("work"),
                "title": "Private bounded projection",
                "language": "und",
                "kind": "edition",
            }
        ],
        "revisions": [
            {
                "id": revision,
                "editionId": identity("edition"),
                "sequence": 1,
                "profileIds": [identity("profile")],
                "importId": identity("import"),
            }
        ],
        "streams": [{"id": stream, "revisionId": revision, "order": 0, "text": extraction.text}],
        "profiles": [
            {
                "id": identity("profile"),
                "version": "0.4.0",
                "nodeTypes": sorted(
                    {b["kind"] for b in extraction.blocks if not b["kind"].startswith("core:")}
                ),
                "featureKeys": ["experiment:evidence"],
                "requiredCapabilities": ["core:positions"],
            }
        ],
        "nodes": [],
        "anchors": [],
        "structures": [],
        "agents": [
            {"id": agent, "kind": "software", "name": "Bounded extraction/mapping experiment"}
        ],
        "assets": [
            {
                "id": identity(f"asset-{i}"),
                "mediaType": a["mediaType"],
                "uri": "local-library:" + a["name"],
                "sha256": a["sha256"],
                "rights": "Private validation only; no redistribution authorization inferred",
            }
            for i, a in enumerate(extraction.assets)
        ],
        "imports": [
            {
                "id": identity("import"),
                "assetIds": [identity(f"asset-{i}") for i in range(len(extraction.assets))],
                "adapter": "bounded-evidence-projection",
                "adapterVersion": "0.4.0",
                "agentId": agent,
                "report": [
                    {
                        "aspect": "selected extracted text",
                        "status": "preserved",
                        "detail": "Exact text from the declared extraction policy, not proof of original visual/source fidelity",
                    }
                ]
                + [
                    {
                        "aspect": "coverage/loss",
                        "status": "transformed" if "Inserted" in loss else "unsupported",
                        "detail": loss,
                    }
                    for loss in extraction.losses
                ],
            }
        ],
    }
    all_blocks = [
        {
            "kind": "core:document",
            "start": 0,
            "end": len(extraction.text),
            "evidence": "selected document scope",
            "attributes": {},
        }
    ] + extraction.blocks
    for i, block in enumerate(all_blocks):
        node = {
            "id": identity(f"node-{i}"),
            "revisionId": revision,
            "type": block["kind"],
            "features": {"experiment:evidence": block["evidence"]},
            "extensions": {"source:attributes": block.get("attributes", {})},
        }
        if block["start"] < block["end"]:
            anchor = {
                "id": identity(f"anchor-{i}"),
                "revisionId": revision,
                "segments": [{"streamId": stream, "start": block["start"], "end": block["end"]}],
            }
            document["anchors"].append(anchor)
            node["anchorId"] = anchor["id"]
        else:
            node["position"] = {"streamId": stream, "offset": block["start"]}
        if block.get("sourceId"):
            primary_asset = next(
                (i for i, a in enumerate(extraction.assets) if a["name"] == "otype.tf"), 0
            )
            node["sourceIds"] = [
                {"assetId": identity(f"asset-{primary_asset}"), "value": block["sourceId"]}
            ]
        document["nodes"].append(node)
    # Each named view preserves the relevant block sequence; overlapping spans do not force nesting.
    for group, kinds in [
        ("pages", {"core:page"}),
        ("paragraphs", {"core:paragraph", "experiment:paragraphCandidate"}),
        ("words", {"core:word"}),
        ("spine", {"experiment:spineDocument"}),
        ("milestones", {"core:milestone"}),
    ]:
        members = [
            {"nodeId": node["id"], "order": order}
            for order, node in enumerate(n for n in document["nodes"] if n["type"] in kinds)
        ]
        if members:
            document["structures"].append(
                {
                    "id": identity(group),
                    "revisionId": revision,
                    "name": "experiment:" + group,
                    "members": members,
                }
            )
    if extraction.notes:
        document["requiredCapabilities"].append("core:annotations")
        document["annotations"] = [
            {
                "id": identity(f"note-{i}"),
                "type": n["type"],
                "agentId": agent,
                "targets": [{"id": identity(f"node-{n['block'] + 1}")}],
                "body": [{"type": "paragraph", "text": n["body"], "marks": n.get("marks", [])}],
                "extensions": {
                    "source:attributes": n.get("attributes", {}),
                    "source:markAttributes": n.get("markAttributes", []),
                    "source:references": n.get("references", []),
                },
            }
            for i, n in enumerate(extraction.notes)
        ]
    if extraction.citations:
        document["requiredCapabilities"].append("core:references")
        entries = [
            {"key": key, "order": i, "targetIds": [identity(f"node-{block + 1}")]}
            for i, (key, block) in enumerate(extraction.citations)
        ]
        scheme = {
            "id": identity("scheme"),
            "name": "experiment:sourceAddress",
            "version": "1.0.0",
            "workId": identity("work"),
            "editionId": identity("edition"),
            "revisionId": revision,
            "entries": entries,
        }
        reference = {
            "schemeId": scheme["id"],
            "schemeVersion": scheme["version"],
            "editionId": scheme["editionId"],
            "revisionId": revision,
            "startKey": entries[0]["key"],
            "endKey": entries[-1]["key"],
        }
        document["schemes"] = [scheme]
        document["resolutions"] = [
            {
                "reference": reference,
                "status": "resolved",
                "targetIds": [e["targetIds"][0] for e in entries],
                "candidates": [],
            },
            {
                "reference": {**reference, "startKey": "absent-key"},
                "status": "unresolved",
                "targetIds": [],
                "candidates": [],
                "reason": "Key absent in selected scheme",
            },
            {
                "reference": {**reference, "schemeVersion": "unloaded-version"},
                "status": "unavailable",
                "targetIds": [],
                "candidates": [],
                "reason": "Exact version not loaded",
            },
        ]
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--usx-zip",
        type=Path,
        action="append",
        default=[],
        help="Additional supplied private USX archive; repeat for each",
    )
    args = parser.parse_args()
    output = args.out.resolve()
    library = args.library.resolve()
    if (
        output == library
        or library in output.parents
        or output == REPO / "specs"
        or REPO / "specs" in output.parents
    ):
        parser.error("Private outputs cannot be written into Library or authoritative specs")
    output.mkdir(parents=True, exist_ok=True)
    pin_file = SPEC_ROOT / "experiments/real-source-results.json"
    pinned_samples = (
        {s["sourceSelection"]: s for s in json.loads(pin_file.read_text())["samples"]}
        if pin_file.exists()
        else {}
    )
    if pin_file.exists():
        for source, expected in (
            json.loads(pin_file.read_text()).get("implementationPins", {}).items()
        ):
            if digest((REPO / source).read_bytes()) != expected:
                raise ValueError(f"Baseline parser differs from pinned experiment: {source}")
    selections = [
        ("of4.txt", extract_plain),
        (
            "The_Tradition_of_the_Throne_Vision_in_th.pdf",
            lambda p: extract_pdf(p, "pdf-paginated-prose"),
        ),
        ("Colwell_rule.pdf", lambda p: extract_pdf(p, "pdf-image-only-pages")),
        ("pg1636-images.epub", extract_epub),
        ("FINAL_TRANSCRIPTION_version104.xml", extract_tei),
        ("ETCBC-pheshitta-tf", extract_tf),
    ]
    sources = {relative: library / relative for relative, _ in selections}
    for i, path in enumerate(args.usx_zip):
        key = "supplied-usx/" + path.name
        sources[key] = path.resolve()
        sample = f"usx-supplied-archive-{i + 1}"
        selections.append((key, lambda p, sample=sample: extract_usx_zip(p, sample)))
    report = {
        "specVersion": "0.4.0",
        "scope": "private bounded experiments; not production adapters",
        "pythonVersion": sys.version.split()[0],
        "packages": {
            n: version(n)
            for n in ("pypdf", "fonttools", "lxml", "pydantic", "text-fabric", "jsonschema")
        },
        "samples": [],
    }
    for relative, extractor in selections:
        selected_source = sources[relative]
        if relative in pinned_samples:
            for pin in pinned_samples[relative]["assets"]:
                source = (
                    selected_source / pin["name"] if selected_source.is_dir() else selected_source
                )
                if digest(source.read_bytes()) != pin["sha256"]:
                    raise ValueError(f"Source checksum differs from pinned experiment: {relative}")
        extraction = extractor(selected_source)
        document = map_to_corpora(extraction)
        errors = checker.validate(document)
        if errors:
            raise AssertionError((extraction.sample, errors))
        assert document["streams"][0]["text"] == extraction.text
        codec_spec = importlib.util.spec_from_file_location("codec", SPEC_ROOT / "xml_codec.py")
        codec = importlib.util.module_from_spec(codec_spec)
        codec_spec.loader.exec_module(codec)
        assert codec.decode(codec.encode(document)) == document
        if extraction.decision:
            extraction.decision = pdf_gate.bind(document, extraction.decision)
        diagnostic = extraction.decision is not None and extraction.decision["status"] != "accepted"
        name = extraction.sample + (".diagnostic.json" if diagnostic else ".json")
        serialized = (
            pdf_gate.artifact(document, extraction.decision) if extraction.decision else document
        )
        (output / name).write_text(json.dumps(serialized, ensure_ascii=False, indent=2) + "\n")
        if relative in pinned_samples and "projectionSha256" in pinned_samples[relative]:
            assert (
                digest((output / name).read_bytes()) == pinned_samples[relative]["projectionSha256"]
            ), extraction.sample
        # Re-read all source bytes and metadata to prove the experiment did not alter them.
        for a in extraction.assets:
            path = selected_source / a["name"] if selected_source.is_dir() else selected_source
            assert digest(path.read_bytes()) == a["sha256"]
            assert path.stat().st_mtime_ns == a["mtimeNs"]
        report["samples"].append(
            {
                "sample": extraction.sample,
                "sourceSelection": relative,
                "assets": extraction.assets,
                "scalars": len(extraction.text),
                "extractedTextSha256": digest(extraction.text.encode("utf-8")),
                "nodes": len(document["nodes"]),
                "anchors": len(document["anchors"]),
                "positions": sum("position" in n for n in document["nodes"]),
                "metrics": extraction.metrics,
                "losses": extraction.losses,
                "conformance": "pass",
                "ingestionDecision": extraction.decision
                or {
                    "status": "not-evaluated",
                    "detail": "Experimental projection, not an adopted import",
                },
                "originalChecksumsAndMtimesUnchanged": True,
                "projectionFile": name,
                "projectionSha256": digest((output / name).read_bytes()),
            }
        )
        print(
            f"PASS {extraction.sample}: {len(document['nodes'])} nodes; {len(extraction.text)} scalars; original unchanged",
            flush=True,
        )
        if extraction.decision:
            print(
                f"PDF ingestion status: {extraction.decision['status']}; unaccepted diagnostic only",
                flush=True,
            )
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"PASS {len(report['samples'])} real-source experiments; private outputs at {output}")


if __name__ == "__main__":
    main()
