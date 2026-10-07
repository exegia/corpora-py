# USX source projection and gap assessment

Status: draft mapping guidance for the independent Corpora contract, reviewed
against the official **USFM-USX-USJ 3.1.1 documentation** on 2026-10-04.
The intended format is USX; the earlier unidentified-format note was a voice
transcription error. The documentation release number is not assumed to equal
the source `<usx version>` attribute: the synthetic assets use `version="3.1"`,
which the linked examples also use. Preserve and validate the actual source
version before conversion. No production USX parser, exporter, upstream schema
validator, or complete marker catalog is implemented here.

The following mappings are Corpora design choices inferred from the documented
source constructs. They do not make USX or Context Fabric the target authority.
USX source XML and Corpora's typed XML transport are separate representations.

## Scripture, peripheral content and identification

The official [document structure](https://docs.usfm.bible/usfm/3.1.1/doc/index.html)
distinguishes scripture from standalone or divided peripheral content. It also
allows introductions, headings and non-verse content. An importer must classify
these explicitly rather than force every block into book/chapter/verse addressing.

| Source concept | Draft target mapping | Scope / limitations |
| --- | --- | --- |
| Scripture source document | a work's edition revision; `usx:book` node and independent layout/scripture structures | catalog reconciliation decides intellectual identity; a filename or book code cannot allocate global identity by itself |
| Standalone peripheral book | separate peripheral work/edition, reusable in collection membership | do not invent a chapter or verse; metadata must say its peripheral role |
| Divided peripheral book | `usx:peripheral` nodes in its own edition, containing ordered layout members | preserve division `id` as asset-scoped source ID/attribute and `alt` as display text; division titles are not IDs |
| Titles, headers, introductions, outlines | heading/paragraph nodes with source styles retained; an introduction structure may group them | running headers and catalog labels must be distinguished from reading text by an explicit import policy |

The [`book` identification](https://docs.usfm.bible/usfm/3.1.1/doc/id.html)
uses a standard three-character book code. Preserve `code`, `style` and optional
description in source metadata, and reconcile the code to a work through a
declared catalog mapping. A code is a source identifier, not a Corpora work ID.
Do not infer an author, translator, publisher, canon membership or versification
authority solely from it. Preserve collection order from verified project
metadata; a single USX book asset cannot establish the entire canon.

Peripheral divisions preserve the documented [`periph` attributes and content](https://docs.usfm.bible/usfm/3.1.1/periph/periph.html).
An edition-bound peripheral work is linked to its publication by a relation or
collection selection, not merged into an unrelated scripture work. The example
front-matter fixture intentionally has its own work/edition and no citation scheme.

## Chapter, verse and reading text

Documented [chapter](https://docs.usfm.bible/usfm/3.1.1/cv/c.html) and
[verse](https://docs.usfm.bible/usfm/3.1.1/cv/v.html) elements carry start/end
identifiers alongside number metadata. A future adapter must pair milestones
under source-version rules, across paragraph boundaries, before creating anchors.
Closing a paragraph must not implicitly close a verse. Broken or ambiguous pairs
must appear in conversion errors/reports; this checker does not parse or pair them.

Store chapter/verse `number`, `altnumber`, `pubnumber`, `sid`, `eid` as source
attributes. Source milestone identifiers may additionally be asset-scoped source
IDs. Citation keys remain strings: a bridge such as `GEN 1:1-2` identifies one
source entry, distinct from a Corpora range spanning two separate entries. The
fixture preserves the bridge rather than inventing independently addressable
verses 1 and 2. Alternate numbering requires its own explicitly scoped scheme
when sufficient mapping evidence exists; printed numbers alone are display
metadata and do not prove an alternate versification mapping.

Paragraphs and poetry lines become independent layout nodes, preserving exact
styles and their numbered levels, while verse anchors may span several such
nodes. Source-derived reading text is stored once in ordered streams. Adapters
must process XML text/tails in document order and state which content is reading
text, metadata, notes or ancillary material. They must report discarded source
formatting whitespace, inserted block/cell separators and normalization. XML
syntax whitespace is not automatically reading whitespace. The hand-authored
fixtures report newline/tab joins; these are explicit projection choices, not
an implemented extraction algorithm.

The [real-source report](experiments/report.md) now adds bounded projections of
Luke 1 from two supplied private USX 3.0 archives. They exercise 80 paired verses
each, actual paragraph/poetry overlap and note insertion/body marks. This does
not implement a production parser/exporter or validate every source marker.
The observed 3.0 source versions are explicit; the 3.1.1 documentation release
is not substituted for their source declaration. Structured cross-reference,
table, sidebar, peripheral and additional `ms` examples remain synthetic because
the supplied archives contain none of those elements.

## Inline content, notes and overlapping milestones

| Source concept | Draft target mapping | Remaining interpretation work |
| --- | --- | --- |
| `char` spans, including nested styles | `usx:char` node with shared anchor; inline structure can preserve nesting; attributes stay in `usx:attributes` | style-to-rendering semantics, `closed` behavior, attribute parsing and nested source reconstruction |
| Footnotes/endnotes and extended notes | attributed annotation at a source-position milestone; structured body blocks/marks; caller/style retained | historical attribution may be unknown; an import agent is provenance, not the original note author |
| Cross-reference notes | annotation preserves source text and `ref loc`; create typed citation relations only after exact target resolution | localized display references and absent target editions must not become fabricated resolved endpoints |
| Quotation/other paired milestones | anchored span node crossing layout boundaries, source pairing/attributes retained | speaker identity reconciliation and source-valid pairing/nesting need an adapter |
| Standalone milestones, optional/page breaks, note insertion points | unanchored `core:milestone` with the optional core position field below | no zero-width text segment; retaining a position does not imply a rendered newline or physical page identity |

The [character documentation](https://docs.usfm.bible/usfm/3.1.1/char/index.html)
defines containers and nested content. Named
[character attributes](https://docs.usfm.bible/usfm/3.1.1/char/attributes.html)
are retained as source strings; lemma/Strong metadata is not automatically a
verified lexical relation. Arbitrary source styles must not be collapsed to
bold/italic if that would discard semantic distinctions.

The documented [footnote](https://docs.usfm.bible/usfm/3.1.1/note/footnote/f.html)
caller is presentation metadata. Note text is stored in annotation bodies,
excluded from verse reading text. Body marks preserve note field styles, with
unmodeled mark attributes retained in the annotation extension. The current
rich-block model cannot directly express all nested note objects or tables;
such content needs a separate content graph or preserved opaque extension plus
an honest unsupported-rendering report.

[Cross-reference notes](https://docs.usfm.bible/usfm/3.1.1/note/crossref/x.html)
can contain several origins and targets. Preserve their grouping and source
reference strings. `usx:references` in the fixture is optional import metadata,
not a validated Corpora `resolution` response. Its unavailable assessment states
why no endpoint relation was emitted. A future resolver must produce the core
resolved/ambiguous/unresolved/unavailable envelope when given a fully scoped
reference; `loc` alone does not provide scheme version or edition/revision scope.

The official [milestone explanation](https://docs.usfm.bible/usfm/3.1.1/ms/index.html)
supports overlapping structures. The draft's span mapping uses existing shared
anchors; [quotation milestones](https://docs.usfm.bible/usfm/3.1.1/ms/qt.html)
retain pair IDs and `who`. A speaker name is source metadata until reconciled to
an agent. The synthetic quotation crosses poetry lines; it does not establish
coverage of every allowed milestone or missing-ID pairing rule.

## Optional point-position capability

The base anchor model deliberately requires nonempty segments. The optional core
position field also serves ordinary document and TEI ingestion:

```json
{
  "type": "core:milestone",
  "position": {"streamId": "urn:example:text", "offset": 18},
  "extensions": {
    "usx:attributes": {"style": "f", "caller": "+"}
  }
}
```

`position.schema.json` validates the field's shape. `offset` is a
Unicode scalar boundary from zero through stream length, inclusive; it is not
an anchor segment. The node has no `anchorId`. The stream must exist in the
node's revision. A bundle or its profile must declare required capability
`core:positions` if it uses this field. A reader without that capability fails
explicitly; the checker recognizes it and verifies shape, scope and bounds.
An importer may instead omit optional positions with an explicit conversion
report, but cannot claim preserved insertion locations.

The synthetic profile ID `urn:corpora:profile:usx-projection:0.4.0` declares the
namespaced types used by these fixtures. It is a minimal draft example, not a
complete or published USX profile registry. Source attributes are optional opaque
extensions: the checker preserves them but does not verify USX marker legality.

## Tables, sidebars and publication semantics

USX [tables](https://docs.usfm.bible/usfm/3.1.1/para/tables/index.html)
use table/row/cell containers. Map these to `usx:table`, `usx:row`, `usx:cell`
nodes in a layout structure; cell anchors reference stored-once text. Preserve
source style, alignment and column span. Source `colspan` is retained as a string
in the fixture, rather than confused with node order. The documented
[cell examples](https://docs.usfm.bible/usfm/3.1.1/char/tables/tc.html) include
spanning cells. The graph checker validates the forest, not table grid geometry;
column overlap, style-number interpretation and grid rendering remain unverified.

Documented [sidebars](https://docs.usfm.bible/usfm/3.1.1/sbar/esb.html) contain
their own paragraphs and other content, with optional category and reference
context. Use a `usx:sidebar` node and its layout members; keep `category` and
`vid` where present. Do not assume sidebar prose belongs to a scripture verse
just because it occurs between verse milestones. A future adapter must report
its inclusion/exclusion policy and may use discontinuous verse anchors where
ancillary content is excluded. Source placement is not physical pagination.

## Executable coverage and gaps

| Fixture/check | What is verified | What is not proved |
| --- | --- | --- |
| `usx-scripture.valid.json` + `.usx` | valid target graph; one bridged verse and quotation cross two poetry lines; intro and character span; note body excluded from main text; bounded insertion position; retained source attributes | parsing, milestone pairing, marker legality, all intro/poetry styles, or original XML reconstruction |
| `usx-peripheral.valid.json` + `.usx` | separate front-matter work; peripheral division; table hierarchy/spanning-cell attributes; sidebar and unresolved reference metadata; end-of-stream position | table geometry, complete peripheral catalog, sidebar scripture inclusion, or actual target reference resolution |
| four invalid point fixtures | out-of-bounds/noninteger position, missing stream and missing required position capability fail for the named reason | no source-level malformed-USX acceptance/rejection tests exist |
| focused projection test | synthetic assets are well-formed XML and match their SHA-256; target projections conform; required-capability rejection and overlap mechanics pass; JSON/Corpora XML round trips preserve extensions | asset well-formedness is not USX conformance or proof the graph was derived from the XML |

Before production use, implement a version-pinned secure source parser, validate
against the applicable upstream rules/schema, test real and malformed assets,
establish whitespace and reading-order policies, reconcile catalog/versification
metadata, verify external references, and compare conversion reports with actual
preservation. Figures, media, ruby/glosses, custom styles, detailed linguistic
attributes and complex note content are not exercised here. Unsupported source
concepts must be retained opaquely where possible and reported; no full USX
support or losslessness claim follows from this draft.
