---
title: Inter-corpus references — CUSX targets
description: Revision-pinned links to arbitrary CUSX nodes and ranges, with USX-style canonical addresses for Bible, Quran and Book of Mormon.
tags:
  - architecture
  - references
  - cusx
status: proposed
type: spec
---

# Inter-corpus references — CUSX targets

**Design update, 2026-10-05.** This replaces the old compact positional token as
the proposed durable cross-corpus link contract. The current TF resolver remains
unchanged. See [reference-forms.md](./reference-forms.md) for compatibility and
implementation status. This document specifies the format; it does not claim a
new resolver, registry or exporter has been implemented.

A paragraph, clause, word, verse, note or other identified content node can link
to any identified node in another document or corpus. The target need not have
the same type or fit the source's hierarchy. A word can link to a paragraph; a
clause can link to a word; a note can link to a verse range.

## 1. Identity, citation and link are distinct

| Concept | Purpose | Example |
| --- | --- | --- |
| Content identity | Exact target within a document | `word-a7`, `clause-b2`, `paragraph-k4` |
| Canonical address | Source-declared address under a named numbering/profile | `MAT 3:1-4`, `QUR 2:255`, `1NE 3:7` |
| Durable link | Exact package revision, document and target | `x-corpora:/greek-nt/1/luke#word-a7` |
| Display label | Reader-facing text; never a lookup key | “third word”, “Al-Baqarah 255” |

IDs are opaque within their declared scope. Do not derive identity from a
citation, label, word ordinal, text offset, TF node number or source filename.
Existing generated `anchor-N` IDs remain usable within their exact package
revision; their spelling does not promise stability after re-conversion.

The scope of a durable endpoint is `(packageId, revision, documentId, anchorId)`.
`packageId` and `revision` come from `CorporaMetadata`; `documentId` is the CUSX
`cx:document/@id`. A document-root target omits the anchor. IDs and revisions
must be bound to an immutable package inventory/checksum by the repository.
Reusing the same revision for changed content is invalid.

## 2. USX linking and the Corpora URI extension

The [USX linking specification](https://ubsicap.github.io/usx/usx3.0.3/linking.html)
provides `link-href`, `link-title` and `link-id` on `char` elements. It supports
project-qualified scripture references, local anchors and resource URIs. User
URI schemes must start with `x-`; therefore this proposal uses `x-corpora`.
These are USX mechanisms; the URI grammar below is a Corpora extension.

```text
x-corpora:/<packageId>/<revision>/<documentId>#<anchorId>
x-corpora:/<packageId>/<revision>/<documentId>
```

Each path segment and fragment is independently UTF-8 percent-encoded; `/`, `#`,
`?` and `%` inside an ID must be encoded. Decode once. Empty path segments,
dot traversal segments, duplicate selector parameters and malformed escapes
are invalid. The URI has no network authority/host. Case is significant for
opaque IDs. `revision` is an opaque repository revision, not the CUSX grammar
version. This is a logical content address, not a filesystem or fetch URL.

Relative links such as `#word-a7` and `luke.usx#word-a7` remain valid inside a
CUSX package. Resolve them against its declared resource inventory, then pin
the endpoint before storing a durable cross-corpus reference. Source XHTML paths
and TF mappings stay in external conversion evidence, not publication links.

```xml
<char style="jmp"
      link-href="x-corpora:/greek-nt/1/luke#word-a7"
      link-title="Target word">linked text</char>
```

A link does not assert translation equivalence, common authorship or alignment.
Those are separately typed relations with explicit provenance. External HTTP
links may remain external; resolving CUSX references must not fetch arbitrary
remote resources or execute embedded instructions.

## 3. Anchoring words, clauses and paragraphs

Use existing CUSX mechanisms, not a mandatory book/chapter/paragraph tree:

| Target | Existing CUSX representation | Target extent |
| --- | --- | --- |
| Word represented as a span | `char style="w" link-id="..."` | Wrapped text |
| Paragraph/block | `para cx:id="..."` | Element content |
| Clause, sentence, word or paragraph across blocks | Paired `cx:boundary` with `unit`, `scheme`, `sid/eid`; anchor on start | Logical paired range |
| Point | Empty `char style="jmp" link-id="..."` | Zero-width position |
| Document | `cx:document/@id` | Whole content document |

`cx` is `urn:corpora:usx-extension:0.1`. For a boundary anchor, the proposed
resolver must return the logical range identified by `(document, unit, scheme,
sid)`, not just its start position. An empty `jmp` anchor remains a point.
`sid/eid` alone are range keys, not automatically link anchors: advertise an
explicit unique `cx:id` on the start when the range is directly linkable.

```xml
<para xmlns:cx="urn:corpora:usx-extension:0.1"
      style="p" cx:id="paragraph-k4" cx:node-type="paragraph">
  <cx:boundary unit="clause" scheme="analysis-v1"
               sid="clause-b2" label="2" cx:id="clause-b2"/>
  A <char style="w" link-id="word-a7" cx:node-type="word">word</char> here.
  <cx:boundary unit="clause" scheme="analysis-v1" eid="clause-b2"/>
</para>
```

Anchor IDs must be unique across `cx:id` and `link-id` in the document, including
its root ID. Producers must reject competing IDs on the same element. Lookup
never silently chooses a similarly named anchor in a different document.

Word, clause, sentence and paragraph boundaries are edition/analysis-specific.
Do not invent a segmentation that the target publication does not provide.
Paragraph and verse are different axes, even when one happens to contain the
other. A clause may cross paragraph or verse boundaries; do not flatten it to
fit a single tree. Discontinuous targets and cross-document fragments require
an explicit logical range index joining declared fragments in reading order.
Until that index is available, return `unavailable` rather than a partial match.
CUSX currently forbids overlapping active ranges on the same `(unit, scheme)`
axis; analyses needing them must declare separate axes/schemes or await a
supported extension, not emit invalid boundaries.

The same mechanism covers link sources. A `char` can wrap linked text; paired
boundaries identify a source clause/range when a relationship cannot be wrapped
without breaking existing markup. The stored relationship has separately scoped
source and target endpoints; a publication rendering may use a `jmp` link at its
source. Arbitrary relations do not require new link attributes on every element.

## 4. Canonical scripture profiles

Keep the familiar USX shape `CODE chapter:verse`, with `CODE chapter` and `CODE`
for containers. A hyphen denotes an inclusive range; comma denotes a selection
list. Cross-chapter ranges repeat the chapter after the hyphen; cross-book
ranges/lists use structured start/end or selection objects, not guessed strings.
Verse labels (including source-declared bridges and suffixes) remain opaque
strings. Only a registry's declared entry order determines expansion.

| Profile | Canonical address | Interpretation | Required context |
| --- | --- | --- | --- |
| `bible` | `MAT 3:1-4` | Matthew, chapter 3, verses 1 through 4 | Bible book-code registry and numbering scheme/version |
| `quran` | `QUR 2:255` | Surah 2, ayah 255 | Quran profile, reading and ayah-numbering scheme/version |
| `book-of-mormon` | `1NE 3:7` | 1 Nephi, chapter 3, verse 7 | Corpora book-code registry and source numbering scheme/version |

Bible codes retain the [USX book-code vocabulary](https://ubsicap.github.io/usx/usx3.0.3/vocabularies.html).
`QUR` and the Book of Mormon codes below are **Corpora profile codes**, not
additions to upstream USX's vocabulary. The CUSX grammar permits their strings;
this document proposes their semantic registry. A generic USX processor is not
required to understand these profiles.

For Quran, `chapter` represents a surah and `verse` an ayah. Preserve the source's
labels and numbering, including its treatment of the basmala. Do not assume a
reading alone determines numbering or convert unnumbered text into ayah 0.
Juz, hizb, rub, manzil and ruku remain independent declared boundary schemes;
they are not extra levels in `QUR surah:ayah` and must not change the ayah address.
Example scheme names are illustrative, not published scholarly authorities.

For Book of Mormon, the proposed Corpora code registry is:

| Code | Book | Code | Book |
| --- | --- | --- | --- |
| `1NE` | 1 Nephi | `2NE` | 2 Nephi |
| `JAC` | Jacob | `ENO` | Enos |
| `JAR` | Jarom | `OMN` | Omni |
| `WOM` | Words of Mormon | `MOS` | Mosiah |
| `ALM` | Alma | `HEL` | Helaman |
| `3NE` | 3 Nephi | `4NE` | 4 Nephi |
| `MOR` | Mormon | `ETH` | Ether |
| `MNI` | Moroni | | |

Book names follow the [published Book of Mormon contents](https://www.churchofjesuschrist.org/study/scriptures/bofm?lang=eng);
the three-character codes are our proposal. In particular, `ENO` also exists
in the Bible vocabulary with a different meaning, so codes are always scoped by
profile. Never resolve `ENO` globally. Introductions and witnesses use document
anchors unless a source explicitly declares a separate canonical scheme.

A canonical reference carries context alongside its string:

```json
{
  "profile": "quran",
  "numbering": {"id": "source-ayah-numbering", "version": "1"},
  "reading": "source-reading",
  "loc": "QUR 2:255",
  "target": {"packageId": "quran-edition", "revision": "1", "documentId": "quran"}
}
```

A work-level citation may omit a concrete target, but remains an unresolved
citation request until an edition is chosen. Paragraph/word/clause selectors
always require a concrete revision and segmentation scheme. Never resolve them
using the numbering of a different translation or analysis.

A canonical link may encode the scoped lookup instead of an anchor:

```text
x-corpora:/quran-edition/1/quran?profile=quran&numbering=source-ayah-numbering&numberingVersion=1&reading=source-reading&loc=QUR%202%3A255
```

This selector form has no fragment. Allow only `profile`, `numbering`,
`numberingVersion`, `reading` and `loc`, each at most once. All except `reading`
are required; `reading` is required for Quran. Percent-encode query values and
reject unknown keys. The selected document must match the requested profile,
numbering/version and reading. This is a serialization of the structured
canonical request, not a resource query.
For Bible/Book of Mormon, omit `reading` unless the selected profile declares it.
After resolution, store the exact endpoint(s) with the original canonical request.
Unqualified `loc` in a CUSX `ref` inherits the current document's profile and
numbering context; a bare `MAT 3:1-4` in ordinary USX retains its upstream meaning.
Do not introduce `word-3` suffixes into the upstream scripture-reference grammar.
Use an anchored word/range in `link-href`, or a structured analysis selector.

## 5. Ranges, segmentation and resolution

Canonical verse ranges expand through the named numbering scheme's ordered
bindings. For opaque labels such as `2-6a`, first consult an exact source entry;
if absent, consult only a declared profile range grammar. Never split a registered
bridge into invented verses. Store an explicit selection list when the source
notation is ambiguous. Node ranges have distinct start/end endpoint objects,
an explicit scope and range/segmentation scheme. They cannot run between unrelated
editions or be formed by lexically sorting opaque IDs.

If a caller asks for the third word or second clause, it must specify the concrete
package/revision, analysis scheme and anchor scope. Count only declared members
of that type in that scheme's order. Resolve to an advertised anchor/range, then
persist the endpoint. Do not skip an absent sentence level and silently flatten
another view. Views can translate ordinals only through an explicit index that
proves both selectors identify the same target.

| Result | Meaning | Storage/consumer behavior |
| --- | --- | --- |
| `resolved` | Exact loaded scope and complete declared target(s) | Preserve ordered targets, type and extent |
| `ambiguous` | More than one valid candidate | Preserve candidates; do not choose implicitly |
| `unresolved` | Scope loaded but address/anchor absent or invalid | Preserve original request and diagnostic |
| `unavailable` | Required revision, profile, scheme or range index not loaded | Preserve pin; do not fall back to latest |

Malformed syntax is an input error; invalid source range pairing is an import
validation failure. A deepest matched ancestor is diagnostic information only:
resolving a missing word must not return its verse as a successful link.
Cross-edition alignment is an explicit relation with provenance, not a fallback
for a failed exact reference. Any source or target may live in another corpus;
each endpoint keeps its own complete scope.

## 6. Compatibility and acceptance checks

`tfref` and `co..._bk..._cl...` remain TF compatibility forms. Decode through the
existing TF resolver using a pinned build, then use external conversion evidence
to map to a published CUSX target. A TF node without such a mapping is unavailable
for CUSX linking. No source TF IDs or source XHTML paths are added to publication
content. The old positional token is not made durable merely by changing its
prefix or adding a USX-looking label.

Implementation acceptance must cover a word-to-paragraph cross-corpus link,
a clause crossing two paragraphs, Quran numbering/reading mismatch, Book of
Mormon/Bible code collision, a changed revision with the same local anchor,
missing segmentation, duplicate anchors, unavailable target packages, source
bridges/ranges and exact XML/JSON link parity. Local links must validate against
the package inventory. External/cross-package strings are preserved without
claiming target existence until the target package is independently loaded.

Current CUSX 0.1.0 already validates grammar, document-local anchors and paired
boundary axes. Its exporter creates anchors for source-identified locations;
it does **not** yet guarantee anchors for every word/clause/paragraph. Its package
validator skips certification of links with URI schemes. The new scoped resolver,
canonical registries, persistent anchor allocation and complete fine-grained
export are follow-up implementation work, not accomplished by this document edit.
