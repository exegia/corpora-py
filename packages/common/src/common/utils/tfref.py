#!/usr/bin/env python3
"""Schema-agnostic reference identifiers for Text-Fabric corpora.

Grammar (short form):
    [corpus[@version]/]<Sec1>[:<Sec2>[:...]][!<otype><i>[-<j>]]
URN form:
    urn:tf:<corpus>[@version]:<Sec1>[:<Sec2>...][!<otype><i>[-<j>]]

Works two ways:
  * with a live Text-Fabric / Context-Fabric ``api`` object (T, L, F, E), or
  * directly from a corpus directory using the bundled stdlib loader, so it
    runs on machines without text-fabric installed.

Design decisions (see SKILL.md / references/grammar.md for the reasoning):
  * section levels come from otext @sectionTypes at runtime — nothing hardcoded
  * @version is optional on input (= "whatever is loaded"), always emitted on
    output when the dataset declares one, so stored references stay durable
  * a node spanning two innermost sections is anchored to the section that
    contains its FIRST slot, in both directions (resolve and serialize)
  * child indices are 1-based, in canonical corpus order
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from urllib.parse import unquote

__all__ = [
    "Ref",
    "parse",
    "resolve",
    "serialize",
    "normalize",
    "to_urn",
    "from_urn",
    "ParseError",
    "SectionNotFound",
    "VersionMismatch",
    "TypeNotInSection",
    "IndexOutOfRange",
    "resolve_ref",
    "node_to_ref",
    "load_corpus",
    "Adapter",
]

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class RefError(ValueError):
    """Base class for every error this module raises."""


class ParseError(RefError):
    pass


class SectionNotFound(RefError, KeyError):  # noqa: N818 - public name, kept
    def __str__(self):  # KeyError quotes its message; undo that
        return RefError.__str__(self)


class VersionMismatch(SectionNotFound):
    """The reference pins a version other than the one that is loaded."""

    def __init__(self, wanted, loaded):
        super().__init__(f"Reference pins version {wanted!r} but the loaded corpus is {loaded!r}.")
        self.wanted, self.loaded = wanted, loaded


class TypeNotInSection(RefError):  # noqa: N818 - public name, kept
    pass


class IndexOutOfRange(RefError, IndexError):  # noqa: N818 - public name, kept
    pass


# --------------------------------------------------------------------------
# Grammar
# --------------------------------------------------------------------------

# Characters that carry meaning in the short form. Percent-encode them when
# they occur *inside* a section value. Spaces are fine in the short form
# (nothing else uses them); the URN form encodes them as %20 too.
RESERVED = "%:/!@"

_SELECTOR_RE = re.compile(r"^(?P<otype>[A-Za-z_][A-Za-z0-9_]*)(?P<i>\d+)(?:-(?P<j>\d+))?$")
_CORPUS_RE = re.compile(r"^(?P<corpus>[A-Za-z0-9_.\-]+)(?:@(?P<version>[A-Za-z0-9_.\-]+))?$")


def _enc(value, urn: bool = False) -> str:
    s = str(value)
    # quote() always encodes '%' and everything not in `safe`; we then only
    # want RESERVED + (space in urn mode) encoded, so build it by hand.
    out = []
    for ch in s:
        if ch in RESERVED or (urn and ch == " "):
            out.append(f"%{ord(ch):02X}")
        else:
            out.append(ch)
    return "".join(out)


def _dec(value: str) -> str:
    return unquote(value)


@dataclass(frozen=True)
class Ref:
    corpus: str | None
    version: str | None
    sections: tuple  # decoded strings; typed later by the corpus
    target_type: str | None
    start: int | None
    end: int | None  # == start for a single node

    @property
    def is_range(self) -> bool:
        return self.target_type is not None and self.end != self.start

    def short(self) -> str:
        head = ""
        if self.corpus:
            head = self.corpus + (f"@{self.version}" if self.version else "") + "/"
        body = ":".join(_enc(s) for s in self.sections)
        return head + body + self._selector()

    def urn(self) -> str:
        if not self.corpus:
            raise ParseError("A URN needs a corpus id; this reference has none.")
        head = "urn:tf:" + self.corpus + (f"@{self.version}" if self.version else "")
        body = ":".join(_enc(s, urn=True) for s in self.sections)
        return head + ":" + body + self._selector()

    def _selector(self) -> str:
        if not self.target_type:
            return ""
        sel = f"!{self.target_type}{self.start}"
        if self.end != self.start:
            sel += f"-{self.end}"
        return sel

    def as_dict(self) -> dict:
        d = asdict(self)
        d["sections"] = list(self.sections)
        return d


def parse(ref: str) -> Ref:
    """Parse a short-form or URN reference into a Ref. Raises ParseError."""
    if not isinstance(ref, str):
        raise ParseError(f"Reference must be a string, got {type(ref).__name__}.")
    s = ref.strip()
    if not s:
        raise ParseError("Empty reference.")
    if s.startswith("urn:tf:"):
        return from_urn(s)

    corpus = version = None
    if "/" in s:
        head, s = s.split("/", 1)
        m = _CORPUS_RE.match(head)
        if not m:
            raise ParseError(
                f"Bad corpus id {head!r} in {ref!r}; expected corpus[@version] "
                "using letters, digits, '_', '.', '-'."
            )
        corpus, version = m.group("corpus"), m.group("version")

    target_type = start = end = None
    if "!" in s:
        s, sel = s.split("!", 1)
        m = _SELECTOR_RE.match(sel)
        if not m:
            raise ParseError(
                f"Bad selector '!{sel}' in {ref!r}; expected !<otype><index>[-<index>] "
                "e.g. !clause2 or !word3-word8 written as !word3-8."
            )
        target_type = m.group("otype")
        start = int(m.group("i"))
        end = int(m.group("j")) if m.group("j") else start
        if start < 1:
            raise ParseError(f"Index must be 1-based; got {start} in {ref!r}.")
        if end < start:
            raise ParseError(f"Range end {end} is before start {start} in {ref!r}.")

    if not s:
        raise ParseError(f"Missing section path in {ref!r}.")
    sections = tuple(_dec(p) for p in s.split(":"))
    if any(p == "" for p in sections):
        raise ParseError(f"Empty section component in {ref!r} (double ':' or trailing ':').")
    return Ref(corpus, version, sections, target_type, start, end)


def from_urn(urn: str) -> Ref:
    if not urn.startswith("urn:tf:"):
        raise ParseError(f"Not a urn:tf reference: {urn!r}")
    rest = urn[len("urn:tf:") :]
    if ":" not in rest:
        raise ParseError(f"URN {urn!r} has no section path after the corpus id.")
    head, body = rest.split(":", 1)
    m = _CORPUS_RE.match(head)
    if not m:
        raise ParseError(f"Bad corpus id {head!r} in URN {urn!r}.")
    # Re-use the short-form parser on the body; corpus/version come from head.
    inner = parse(body)
    return Ref(
        m.group("corpus"),
        m.group("version"),
        inner.sections,
        inner.target_type,
        inner.start,
        inner.end,
    )


def to_urn(ref) -> str:
    return (parse(ref) if isinstance(ref, str) else ref).urn()


# --------------------------------------------------------------------------
# Corpus adapters
# --------------------------------------------------------------------------


class Adapter:
    """Uniform view over a corpus, whether it is a live TF api or .tf files.

    Subclasses implement the primitive queries; everything above this layer
    (anchoring, indexing, caching) is shared.
    """

    section_types: tuple
    section_feats: tuple
    version: str | None
    slot_type: str

    # --- primitives ------------------------------------------------------
    def otype(self, n: int) -> str:
        raise NotImplementedError

    def slots(self, n: int) -> tuple:
        raise NotImplementedError  # (first, last)

    def node_from_section(self, sec: tuple, lang=None):
        raise NotImplementedError

    def section_from_node(self, n: int, lang=None) -> tuple:
        raise NotImplementedError

    def candidates(self, sec_node: int, otype: str) -> set:
        raise NotImplementedError

    def feature_type(self, feat: str) -> str:
        raise NotImplementedError  # 'int' | 'str'

    def text(self, n: int) -> str:
        return ""

    def all_types(self) -> set:
        raise NotImplementedError

    # --- shared logic ----------------------------------------------------
    def typed_sections(self, sections: Sequence[str]) -> tuple:
        """Cast section strings to the value types of the section features."""
        if len(sections) > len(self.section_types):
            raise SectionNotFound(
                f"Section path {tuple(sections)} has {len(sections)} levels but this corpus "
                f"only has {len(self.section_types)}: {self.section_types}."
            )
        out: list = []
        for value, feat in zip(sections, self.section_feats, strict=False):
            if self.feature_type(feat) == "int":
                try:
                    out.append(int(value))
                except ValueError as exc:
                    raise SectionNotFound(
                        f"Section feature '{feat}' is numeric but got {value!r}."
                    ) from exc
            else:
                out.append(value)
        return tuple(out)

    _children_cache: dict[tuple[int, str], tuple] | None = None

    def children(self, sec_node: int, otype: str) -> tuple:
        """Nodes of `otype` anchored in `sec_node`, canonical order (cached).

        Anchoring = the node's first slot lies inside the section's slot
        range. That is deliberately not the same as "fully embedded": a
        clause that starts in verse 2 and ends in verse 3 belongs to verse 2,
        and only verse 2, so every node gets exactly one address.
        """
        if self._children_cache is None:
            self._children_cache = {}
        hit = self._children_cache.get((sec_node, otype))
        if hit is not None:
            return hit
        lo, hi = self.slots(sec_node)
        keep = []
        for n in self.candidates(sec_node, otype):
            f, last = self.slots(n)
            if lo <= f <= hi:
                keep.append((int(f), -int(last), int(n)))
        keep.sort()
        # Plain ints on purpose: loaders hand back numpy scalars, which do
        # not JSON-serialise and compare unequally in surprising places.
        result = tuple(n for _, _, n in keep)
        self._children_cache[(sec_node, otype)] = result
        return result

    def index_of(self, sec_node: int, otype: str, node: int) -> int:
        kids = self.children(sec_node, otype)
        try:
            return kids.index(node) + 1
        except ValueError as exc:
            raise TypeNotInSection(
                f"Node {node} ({otype}) is not anchored in section node {sec_node}."
            ) from exc

    def anchor_section(self, node: int, lang=None) -> tuple:
        """(section_node, section_tuple) for the innermost section that
        contains the node's first slot; falls back to outer levels when the
        innermost level has gaps (e.g. front matter before chapter 1)."""
        first, _ = self.slots(node)
        # Section of the first slot, deepest level available.
        sec = self.section_from_node(first, lang=lang)
        sec = tuple(s for s in sec if s is not None)
        while sec:
            sec_node = self.node_from_section(sec, lang=lang)
            if sec_node:
                return sec_node, sec
            sec = sec[:-1]
        raise SectionNotFound(f"Node {node} (slot {first}) is not inside any section.")


class TFApiAdapter(Adapter):
    """Wraps a live text-fabric or context-fabric ``api``."""

    def __init__(self, api, version: str | None = None):
        self.api = api
        t_api, f_api = api.T, api.F
        self.section_types = tuple(t_api.sectionTypes)
        self.section_feats = tuple(getattr(t_api, "sectionFeats", self.section_types))
        self.slot_type = f_api.otype.slotType
        self.version = version or self._dataset_version()

    def _dataset_version(self):
        try:
            return self.api.TF.features["otype"].metaData.get("version") or None
        except Exception:
            return None

    def otype(self, n):
        t = self.api.F.otype.v(n)
        return None if t is None else str(t)

    def slots(self, n):
        if self.otype(n) == self.slot_type:
            return (int(n), int(n))
        s = self.api.E.oslots.s(n)
        return (int(s[0]), int(s[-1]))

    def node_from_section(self, sec, lang=None):
        kw = {"lang": lang} if lang else {}
        try:
            node = self.api.T.nodeFromSection(tuple(sec), **kw)
        except Exception:  # noqa: BLE001 - see section_from_node
            node = self._section_index().get(tuple(sec))
        return None if node is None else int(node)

    _sec_index = None

    def _section_index(self):
        """tuple(headings) -> node, built from the section features. Only used
        when the loader's own T.nodeFromSection is unavailable."""
        if self._sec_index is None:
            index = {}
            for depth, stype in enumerate(self.section_types, 1):
                for n in self.api.F.otype.s(stype):
                    key = self._section_from_features(n)[:depth]
                    if None not in key:
                        index.setdefault(tuple(key), int(n))
            self._sec_index = index
        return self._sec_index

    def section_from_node(self, n, lang=None):
        kw = {"lang": lang} if lang else {}
        try:
            return tuple(self.api.T.sectionFromNode(n, **kw))
        except Exception:  # noqa: BLE001
            # Some loaders (cfabric on a one-level hierarchy) fail here;
            # derive the heading tuple from the section features directly.
            return self._section_from_features(n)

    def _section_from_features(self, n):
        out = []
        own_type = self.otype(n)
        for stype, feat in zip(self.section_types, self.section_feats, strict=False):
            holder = n if own_type == stype else next(iter(self.api.L.u(n, otype=stype)), None)
            if holder is None:
                out.append(None)
                continue
            try:
                out.append(self.api.Fs(feat).v(holder))
            except Exception:  # noqa: BLE001
                out.append(None)
        return tuple(out)

    def candidates(self, sec_node, otype):
        lapi = self.api.L
        cands = set(lapi.d(sec_node, otype=otype))
        if otype != self.slot_type:
            lo, hi = self.slots(sec_node)
            # Catch nodes that start inside the section but spill past it:
            # L.d may or may not include them depending on the loader.
            for s in range(lo, hi + 1):
                cands.update(lapi.u(s, otype=otype))
        return cands

    def feature_type(self, feat):
        try:
            return self.api.TF.features[feat].metaData.get("valueType", "str")
        except Exception:
            return "str"

    def text(self, n):
        try:
            return self.api.T.text(n)
        except Exception:
            return ""

    def all_types(self):
        return set(self.api.F.otype.all)


# --- stdlib loader ----------------------------------------------------------

_SPEC_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")


def _read_tf(path):
    """Return (meta, data_lines) for a .tf file. Minimal, tolerant reader."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    meta, i = {}, 1
    while i < len(lines) and lines[i].startswith("@"):
        k, _, v = lines[i][1:].partition("=")
        meta[k] = v
        i += 1
    if i < len(lines) and lines[i] == "":
        i += 1
    return meta, lines[i:]


def _spans(spec):
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.append((int(a), int(b or a)))
    return out


class DirAdapter(Adapter):
    """Reads otype/oslots/otext and the section features straight from .tf
    files. No text-fabric needed. Enough for addressing; not a full API."""

    def __init__(self, directory: str, version: str | None = None):
        self.dir = directory
        if not os.path.isfile(os.path.join(directory, "otype.tf")):
            raise FileNotFoundError(
                f"No otype.tf in {directory}; point at the directory that holds it."
            )
        self._load_otype()
        self._load_oslots()
        self._load_otext()
        self._load_section_feats()
        self.version = version or self._otype_meta.get("version") or None

    # loading -------------------------------------------------------------
    def _load_otype(self):
        meta, data = _read_tf(os.path.join(self.dir, "otype.tf"))
        self._otype_meta = meta
        blocks, cursor = [], 1
        for line in data:
            f = line.split("\t")
            if len(f) >= 2 and _SPEC_RE.match(f[0]):
                for lo, hi in _spans(f[0]):
                    blocks.append((lo, hi, f[1]))
                    cursor = hi + 1
            else:
                blocks.append((cursor, cursor, f[0]))
                cursor += 1
        blocks.sort()
        self._blocks = blocks
        self._starts = [b[0] for b in blocks]
        self.slot_type = blocks[0][2]
        self.max_node = max(b[1] for b in blocks)
        self._by_type = {}
        for lo, hi, t in blocks:
            self._by_type.setdefault(t, []).append((lo, hi))

    def _load_oslots(self):
        _, data = _read_tf(os.path.join(self.dir, "oslots.tf"))
        self._oslots = {}
        cursor = self.max_slot_guess = None
        # oslots may use explicit node specs or implicit numbering starting
        # at maxSlot+1; compute maxSlot from otype first.
        max_slot = max(hi for lo, hi, t in self._blocks if t == self.slot_type)
        cursor = max_slot + 1
        for line in data:
            f = line.split("\t")
            if len(f) >= 2 and _SPEC_RE.match(f[0]):
                nodes, spec = _spans(f[0]), f[1]
                # TF semantics: an explicit node spec moves the implicit
                # cursor past it, so the next bare line is node max+1.
                cursor = max(b for _, b in nodes) + 1
            else:
                nodes, spec = [(cursor, cursor)], f[0]
                cursor += 1
            sl = _spans(spec)
            lo = min(a for a, _ in sl)
            hi = max(b for _, b in sl)
            for a, b in nodes:
                for n in range(a, b + 1):
                    self._oslots[n] = (lo, hi)
        self.max_slot = max_slot
        # Per-type index sorted by first slot, so section lookups bisect
        # instead of scanning (matters at BHSA scale).
        self._by_first = {}
        for t, ranges in self._by_type.items():
            if t == self.slot_type:
                continue
            lst = []
            for a, b in ranges:
                for n in range(a, b + 1):
                    if n in self._oslots:
                        lst.append((self._oslots[n][0], self._oslots[n][1], n))
            lst.sort()
            self._by_first[t] = lst

    def _load_otext(self):
        meta, _ = _read_tf(os.path.join(self.dir, "otext.tf"))
        st = meta.get("sectionTypes", "")
        sf = meta.get("sectionFeatures", "")
        self.section_types = tuple(x.strip() for x in st.split(",") if x.strip())
        self.section_feats = (
            tuple(x.strip() for x in sf.split(",") if x.strip()) or self.section_types
        )
        if not self.section_types:
            raise SectionNotFound(
                "otext.tf declares no @sectionTypes; the corpus has no addressable "
                "sections (run text-fabric-validator to see why)."
            )

    def _load_section_feats(self):
        self._feat_meta, self._feat_val = {}, {}
        for feat in self.section_feats:
            path = os.path.join(self.dir, feat + ".tf")
            if not os.path.isfile(path):
                raise SectionNotFound(f"Section feature file {feat}.tf is missing.")
            meta, data = _read_tf(path)
            self._feat_meta[feat] = meta
            vals, cursor = {}, 1
            is_int = meta.get("valueType") == "int"
            for line in data:
                f = line.split("\t")
                if len(f) >= 2 and _SPEC_RE.match(f[0]):
                    spans, v = _spans(f[0]), f[1]
                else:
                    spans, v = [(cursor, cursor)], f[0]
                    cursor += 1
                v = v.replace("\\t", "\t").replace("\\n", "\n").replace("\\\\", "\\")
                if is_int:
                    try:
                        v = int(v)
                    except ValueError:
                        pass
                for a, b in spans:
                    for n in range(a, b + 1):
                        vals[n] = v
                    cursor = b + 1
            self._feat_val[feat] = vals
        # section lookup table: tuple -> node, built per level
        self._sec_index = {}
        for depth, (stype, _feat) in enumerate(
            zip(self.section_types, self.section_feats, strict=False), 1
        ):
            for lo, hi in self._by_type.get(stype, []):
                for n in range(lo, hi + 1):
                    key = self._heading(n, depth)
                    if key is not None:
                        self._sec_index.setdefault(key, n)

    def _heading(self, n, depth):
        """Heading tuple of section node n at its own level (depth)."""
        first, _ = self.slots(n)
        parts = []
        for d in range(depth):
            stype, feat = self.section_types[d], self.section_feats[d]
            if d == depth - 1:
                holder = n
            else:
                holder = self._section_node_containing_slot(first, stype)
                if holder is None:
                    return None
            v = self._feat_val[feat].get(holder)
            if v is None:
                return None
            parts.append(v)
        return tuple(parts)

    def _section_node_containing_slot(self, slot, stype):
        lst = self._by_first.get(stype, [])
        i = bisect.bisect_right(lst, (slot, float("inf"), float("inf")))
        # Walk back over nodes starting at or before `slot`; sections don't
        # overlap, so the first one that still covers `slot` is the answer
        # and the walk is short.
        while i > 0:
            i -= 1
            f, last, n = lst[i]
            if f <= slot <= last:
                return n
        return None

    # primitives ----------------------------------------------------------
    def otype(self, n):
        i = bisect.bisect_right(self._starts, n) - 1
        if i < 0:
            return ""
        lo, hi, t = self._blocks[i]
        return t if lo <= n <= hi else ""

    def slots(self, n):
        if self.otype(n) == self.slot_type:
            return (n, n)
        if n not in self._oslots:
            raise SectionNotFound(f"Node {n} has no oslots entry (no position in the corpus).")
        return self._oslots[n]

    def node_from_section(self, sec, lang=None):
        return self._sec_index.get(tuple(sec))

    def section_from_node(self, n, lang=None):
        first, _ = self.slots(n)
        out = []
        for stype, feat in zip(self.section_types, self.section_feats, strict=False):
            holder = self._section_node_containing_slot(first, stype)
            out.append(None if holder is None else self._feat_val[feat].get(holder))
        return tuple(out)

    def candidates(self, sec_node, otype):
        lo, hi = self.slots(sec_node)
        if otype == self.slot_type:
            return set(range(lo, hi + 1))
        lst = self._by_first.get(otype, [])
        i = bisect.bisect_left(lst, (lo, 0, 0))
        j = bisect.bisect_right(lst, (hi, float("inf"), float("inf")))
        return {n for _, _, n in lst[i:j]}

    def feature_type(self, feat):
        return self._feat_meta.get(feat, {}).get("valueType", "str")

    def all_types(self):
        return set(self._by_type)


def load_corpus(source, version: str | None = None) -> Adapter:
    """Accept a directory path, a live api object, or an Adapter."""
    if isinstance(source, Adapter):
        return source
    if isinstance(source, str):
        return DirAdapter(source, version=version)
    if all(hasattr(source, a) for a in ("T", "L", "F", "E")):
        return TFApiAdapter(source, version=version)
    raise TypeError("source must be a corpus directory, a TF api object, or an Adapter")


# --------------------------------------------------------------------------
# Resolve / serialize / normalize
# --------------------------------------------------------------------------


def resolve(ref, source, lang=None):
    """Return a node (int) or, for a range, a list of nodes."""
    r = parse(ref) if isinstance(ref, str) else ref
    c = load_corpus(source)
    if r.version and c.version and r.version != c.version:
        raise VersionMismatch(r.version, c.version)
    sec = c.typed_sections(r.sections)
    sec_node = c.node_from_section(sec, lang=lang)
    if not sec_node:
        raise SectionNotFound(
            f"Section {sec} not found. Levels here are {c.section_types}; "
            f"check spelling/language of the headings."
        )
    if not r.target_type:
        return sec_node
    if r.target_type not in c.all_types():
        raise TypeNotInSection(
            f"No node type {r.target_type!r} in this corpus. Types: {sorted(c.all_types())}."
        )
    kids = c.children(sec_node, r.target_type)
    if not kids:
        raise TypeNotInSection(f"Section {sec} contains no {r.target_type!r} nodes.")
    if r.end > len(kids):
        raise IndexOutOfRange(
            f"Index {r.end} out of range: section {sec} has {len(kids)} {r.target_type!r} node(s)."
        )
    if r.is_range:
        return list(kids[r.start - 1 : r.end])
    return kids[r.start - 1]


def serialize(node, source, corpus_id=None, lang=None, form="short", version=None) -> str:
    """Node (or [first, last] of one otype) -> reference string.

    Emits the dataset version whenever one is known, so the result is durable
    even if the caller never thought about versions.
    """
    c = load_corpus(source)
    ver = version or c.version
    if isinstance(node, (list, tuple)):
        if not node:
            raise IndexOutOfRange("Empty node list.")
        first, last = node[0], node[-1]
        t = c.otype(first)
        if c.otype(last) != t:
            raise TypeNotInSection("A range must consist of nodes of one type.")
        sec_node, sec = c.anchor_section(first, lang=lang)
        i = c.index_of(sec_node, t, first)
        j = c.index_of(sec_node, t, last)  # raises if last is anchored elsewhere
        r = Ref(corpus_id, ver, tuple(str(s) for s in sec), t, i, j)
    else:
        t = c.otype(node)
        if not t:
            raise SectionNotFound(f"Node {node} does not exist.")
        if t in c.section_types:
            depth = c.section_types.index(t) + 1
            sec = c.section_from_node(node, lang=lang)[:depth]
            r = Ref(corpus_id, ver, tuple(str(s) for s in sec), None, None, None)
        else:
            sec_node, sec = c.anchor_section(node, lang=lang)
            i = c.index_of(sec_node, t, node)
            r = Ref(corpus_id, ver, tuple(str(s) for s in sec), t, i, i)
    return r.urn() if form == "urn" else r.short()


def normalize(ref, source, lang=None, form="short") -> str:
    """parse -> resolve -> serialize: canonical spelling with version filled in."""
    r = parse(ref) if isinstance(ref, str) else ref
    nodes = resolve(r, source, lang=lang)
    if isinstance(nodes, list):
        nodes = [nodes[0], nodes[-1]]
    return serialize(nodes, source, corpus_id=r.corpus, lang=lang, form=form, version=r.version)


# Backwards-compatible names from the original design note.
def resolve_ref(ref_str, tf_app):
    return resolve(ref_str, tf_app)


def node_to_ref(node, tf_app, corpus_id=None):
    return serialize(node, tf_app, corpus_id=corpus_id)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _cli(argv=None):
    p = argparse.ArgumentParser(description="Text-Fabric schema-agnostic references")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("parse", help="parse a reference (no corpus needed)")
    s.add_argument("ref")

    s = sub.add_parser("resolve", help="reference -> node(s)")
    s.add_argument("corpus_dir")
    s.add_argument("ref")
    s.add_argument(
        "--text", action="store_true", help="also print the slot text (needs text-fabric)"
    )

    s = sub.add_parser("serialize", help="node(s) -> reference")
    s.add_argument("corpus_dir")
    s.add_argument("nodes", nargs="+", type=int, help="one node, or first and last node of a range")
    s.add_argument("--corpus", help="corpus id to prefix")
    s.add_argument("--urn", action="store_true")

    s = sub.add_parser("normalize", help="canonical spelling with version filled in")
    s.add_argument("corpus_dir")
    s.add_argument("ref")
    s.add_argument("--urn", action="store_true")

    s = sub.add_parser("info", help="section levels, types and version of a corpus")
    s.add_argument("corpus_dir")

    a = p.parse_args(argv)
    try:
        if a.cmd == "parse":
            r = parse(a.ref)
            d = r.as_dict()
            d["short"] = r.short()
            if r.corpus:
                d["urn"] = r.urn()
            print(json.dumps(d, indent=2, ensure_ascii=False))
            return 0
        c = load_corpus(a.corpus_dir)
        if a.cmd == "info":
            print(
                json.dumps(
                    {
                        "section_types": list(c.section_types),
                        "section_features": list(c.section_feats),
                        "slot_type": c.slot_type,
                        "node_types": sorted(c.all_types()),
                        "version": c.version,
                    },
                    indent=2,
                )
            )
        elif a.cmd == "resolve":
            n = resolve(a.ref, c)
            out = {
                "ref": a.ref,
                "nodes": n if isinstance(n, list) else [n],
                "otype": c.otype(n[0] if isinstance(n, list) else n),
            }
            print(json.dumps(out))
        elif a.cmd == "serialize":
            node = a.nodes[0] if len(a.nodes) == 1 else [a.nodes[0], a.nodes[-1]]
            print(serialize(node, c, corpus_id=a.corpus, form="urn" if a.urn else "short"))
        elif a.cmd == "normalize":
            print(normalize(a.ref, c, form="urn" if a.urn else "short"))
        return 0
    except RefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli())
