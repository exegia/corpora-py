# Corpus Document 0.4.0

Normative terms MUST, SHOULD and MAY express requirements. A Corpus Document is
a transport bundle of a logical graph, not a database dump or a Context Fabric
object. JSON shape and graph conformance are both required. Schema success alone
is insufficient. Fixtures are synthetic excerpts demonstrating mechanics;
Bible and Quran fixtures are not scholarly numbering authorities or complete editions.

## Identity and bibliographic model

Every entity has an opaque persistent URN `id`, allocated by the Corpora identity
authority or an explicitly delegated importer namespace. IDs MUST NOT be derived
from a citation, title, route, text offset or source-local ID. The sample fixtures
use illustrative URNs. IDs are globally unique across entity kinds and bundles;
the checker detects local collisions, while repositories enforce global uniqueness.
A bundle ID identifies the transport boundary and cannot equal an entity ID.

A work is an intellectual identity independent of its editions, translations and
recensions. An edition belongs to one work and describes a realization; its kind
states intent rather than claiming textual equivalence. A collection contains
ordered membership records pointing to works, optionally selecting an edition.
The same work can appear in multiple canons, in different orders. Membership
order is a nonnegative integer unique in the collection; gaps are permitted.
Repeated work membership is permitted where a collection intentionally repeats a
work. Collections do not own or duplicate works.

Agents are people, organizations or software. Contributions connect an agent to
an entity with a namespaced role, including `core:author`, `core:translator`,
`core:editor`, `core:publisher`. These are bibliographic contributions, distinct
from an import agent or annotation attribution. Unknown historical authors may
be represented as an explicitly uncertain named agent with an extension; do not
invent a known person.

Aliases and routes are presentation/discovery metadata. They may collide and
change. Source IDs are `(assetId, value)` pairs and are not Corpora identity.
Citation keys are opaque strings scoped to a reference scheme, never sort keys.
No implicit primary collection, edition, citation scheme or route exists.

## Immutable revision and text model

An edition has immutable revisions, each with a unique increasing `sequence`.
An optional predecessor belongs to the same edition with a lower sequence.
A revision freezes its streams, anchors, nodes, structures, profile versions,
reference schemes and import provenance. Changing any of those creates a new
revision and new IDs for changed records. Unchanged bibliographic entities may
keep their IDs. Do not assume a node ID survives re-import; record explicit
correspondence relations when known. Mutable annotations and catalog metadata
must be versioned independently by storage implementations.

Streams store text once per revision in explicit `order`, unique within the
revision. A stream can be empty. Stream ordering has no implicit separator:
whitespace and line breaks are stored exactly in `text`. Adapters must declare
any joins, inserted separators, OCR corrections or Unicode normalization in their
conversion report. Consumers MUST NOT silently trim or normalize text.

Offsets count Unicode scalar values, zero-based, half-open `[start,end)`.
No UTF-8 byte or UTF-16 code-unit indexing is allowed. Unpaired surrogates are
invalid text. Combining marks count separately: `A😀é\n` has five scalars.
JavaScript implementations must convert code units to scalar indices; Python
code-point indexing works only after rejecting surrogates. NFC/NFD normalization
changes offsets and requires a new revision. UTF-8 is the JSON/XML wire encoding.

An anchor has one or more nonempty segments pointing to streams in its revision.
Segments are ordered by `(stream.order, start)`, nonoverlapping within an anchor,
and bounded by stream length. Discontinuous coverage is explicit, never implied
by a parent tree. Extracting an anchor concatenates its exact segment slices
without inserted spaces; a reading display MAY show gaps without changing stored
text. Adjacent segments are valid; canonical writers SHOULD merge them. Distinct
anchors may overlap freely, and multiple nodes can share one anchor. Empty
milestones or non-text objects have no anchor; do not manufacture zero-width text.
Nodes MAY instead carry `position: {streamId, offset}` for a point in their
revision's stream, including an empty page, note insertion or line-break marker.
The scalar offset is between zero and stream length, inclusive. `position` and
`anchorId` are mutually exclusive. Using positions requires `core:positions`.
Several points can share an offset; named-structure order distinguishes their
sequence. A point does not imply an inserted character or reconstructed layout.

Typed content nodes can represent verses, paragraphs, sentences, clauses, words,
headings, physical pages, images or other profile types. A node optionally links
to an anchor and asset/locator. `locator` is opaque descriptive physical metadata;
a profile must define its interpretation before a client uses coordinates.
A page and a paragraph use independent anchors, so a paragraph can cross pages.
Containers can anchor their complete span without duplicating text.

Named structures are ordered forests over nodes in one revision. Membership
contains a node, sibling order and optional parent. A node appears at most once
in a particular structure, but may appear in several structures. Parents must
be members of that same structure; cycles and duplicate sibling positions fail.
There is no universal content tree and no requirement that parent anchors contain
child anchors. Profiles may impose containment when needed. An empty forest is
valid. Flat order is a special case of the same model.

## Profiles, features and extensions

The base single-document case needs only a bundle, work, edition, revision and
stream. Optional arrays may be omitted. Profiles are unnecessary for core types.
This avoids requiring collections, verse hierarchies or linguistic segmentation
for a plain document.

Namespaced keys use `namespace:name`. `core` is reserved to this specification.
Draft core node types include document, section, heading, paragraph, sentence,
clause, word, verse, page, figure and milestone. Other core type names are not
allocated by this draft. A profile declares its version, node types, feature
keys and required capabilities. Profile IDs identify immutable declarations;
changing a declaration allocates a new ID. Namespaces should be registered to
avoid collisions before publication; URI ownership rules remain a review item.
Features carry JSON values; this draft does not type-check profile-specific
values. A profile author must publish separate feature constraints if needed.

The checker supports `core:text`, `core:anchors`, `core:structures`,
`core:references`, `core:relations`, `core:annotations`, `core:positions`. Every reader MUST fail
explicitly when any bundle/profile required capability is unsupported. Consumers
should pass their actual capability set rather than assume the checker set.
Required capabilities are a declaration of processing requirements, not automatic
inference from field presence. A writer must declare capabilities required to
interpret its payload; optional records may be preserved without interpretation.
The optional position capability is format independent. Real PDF/TEI experiments
and [USX adapter guidance](usx-adapter.md) use the same logical field. A reader
without position handling must reject this required capability explicitly.

Unknown optional data belongs in namespaced `extensions` and MUST survive
JSON/XML/database round trips with its JSON value semantics intact. Unknown
features may be preserved without interpreting them. Unknown top-level fields
fail schema validation so typos cannot disappear silently. Unknown required
capabilities cannot be converted into optional extensions. No promise of source
format losslessness follows from extension preservation.

## Annotation and relation model

Annotations have attributed, typed targets and rich block bodies. Blocks support
paragraph, heading and code text with scalar-indexed marks. Marks may overlap;
link marks carry an entity endpoint. This is structured content, not arbitrary
executable HTML. More block formats can be represented through optional extensions
or a future version; clients must preserve unsupported content and state rendering
limits. Commentary may target nodes, anchors or other entities, including a
separate commentary work connected by a relation when it needs its own editions.

Relations are attributed typed hyperedges with nonempty sources and targets,
optional confidence and evidence assets. `core:alignment` supports many-to-many
coverage without asserting identity or transitivity. `core:cites`,
`core:translationOf` and `core:correspondsTo` are suggested relationship types.
Profile-defined types can specify direction and interpretation; do not infer an
inverse relationship automatically. A relation can connect different revisions,
works or corpora. A local endpoint must exist. An external endpoint includes
`bundleId`; unloaded external bundles are explicit unresolved boundaries. The
checker can accept loaded external bundles for existence checks; absence is not
proof of a valid external target. Deployment validation must fetch the pinned
external bundle or report unverified external links, never label them verified.

## Citations and reference resolution

A scheme has an immutable ID and version and explicit work, edition and revision
scope. Its entries map a unique string `key` to ordered target node IDs; entry
`order` is unique and independent of the key. `2a`, `title`, missing numbers,
zero labels and alternate book numbering need no integer coercion. Multiple keys
may target the same node. A key may target several nodes as one resolved coverage.
Different numbering traditions use different schemes, even on the same revision.
Different edition segmentation uses different revisions and explicit alignment.

A reference specifies scheme ID/version, edition/revision and `startKey`, with an
optional inclusive `endKey`. A range follows scheme entry order, includes both
endpoints and deduplicates target IDs in first-occurrence order. It never uses
lexical key ordering or text offsets. Reversed ranges are unresolved. This draft
supports one contiguous citation range per reference; discontinuous references
are a list of references, distinct from discontinuous text anchors.

Resolution returns exactly one of these outcomes:

| Outcome | Required meaning |
| --- | --- |
| resolved | Exact scheme and scope available; keys present; targets equal the ordered mapping; candidates empty |
| ambiguous | Exact scheme available but caller parsing/alias selection has at least two competing target sets; no selected targets; reason required |
| unresolved | Scheme available but key/range cannot resolve; no targets/candidates; reason required |
| unavailable | Exact scheme version or edition/revision absent; no targets/candidates; reason required |

An ambiguous response carries candidate node sets, all within the requested
revision. The checker verifies their existence and scope but cannot verify the
upstream alias parser rationale. Never silently fall back to a default edition,
newer revision, approximate numbering or the first candidate. Assets, profiles
and schemes are loaded by exact ID; unavailable is distinct from unknown key.

## Shape and graph conformance

`document.schema.json` is Draft 2020-12. The extracted profile and resolution
entry schemas refer to its definitions by immutable URN and resolve offline.
The fixture index names every JSON fixture and its expected error prefix or null
for success. Invalid cases must fail for the named reason, not merely any reason.

The checker enforces local identity uniqueness, typed foreign keys, edition/work
membership, revision predecessor order, stream ordering/scalar validity, anchor
scope/bounds/order, node profile declarations, named forest constraints,
attribution, annotation mark bounds, scheme scope/key/order/target validity and
resolution output consistency. Required capabilities fail explicitly. It also
checks JSON and XML representation round trips, including unknown extensions.

Persistence conformance additionally MUST enforce append-only revision content,
global ID uniqueness, checksums against fetched source bytes, namespace ownership,
profile-specific semantics and verified external target availability. These are
not proved by an isolated document checker. Import checksums in fixtures are
illustrative values, not evidence of fetched production assets. Full adapters,
citation parsing, source reconstruction and server/database enforcement remain
future implementation work.

## Sources and adapters

PDF ingestion MUST pass the separate [quality and atomic acceptance policy](pdf-ingestion-policy.md).
Insufficient or failed recovery rejects the whole import. A graph that validates
by shape/invariants may remain only an unaccepted diagnostic; bounded page samples
and unverified reading fidelity cannot produce an accepted partial corpus. An
accepted decision binds the exact source and candidate and requires complete page
coverage. Persist accepted revisions atomically with that decision; diagnostic
records remain outside the accepted corpus namespace.

Assets carry media type, URI, SHA-256 of original bytes and optional rights.
Import provenance names exact adapter/version, agent, source assets and an honest
report per relevant aspect: preserved, transformed, omitted or unsupported, with
specific details. Profile/source IDs and locators retain original labels without
becoming canonical identity. A conversion that loses unsupported semantics must
say so; no adapter may claim full losslessness merely because text survives.
Raw assets remain separately retained under their rights policy.

| Adapter source | Mapping rule and required report |
| --- | --- |
| Text-Fabric | ordered slots → stream plus explicit slot-to-scalar map; node slot sets → contiguous/discontinuous anchors; features → namespaced values; edges → typed relations; report slot joins, omitted features and metadata |
| Context Fabric beta | pin actual dependency version; map its text/fragments, nodes and features through an explicit adapter; do not assume its object shape is stable or authoritative; report unavailable graph concepts |
| TEI/XML | preserve original bytes; text/tails and normalization policy → stream; XML IDs → asset-scoped source IDs; milestones/standoff spans → structures/anchors; report apparatus, entities and markup that cannot be mapped |
| USX | [USX mapping assessment](usx-adapter.md) defines a draft projection of 3.1.1 documentation concepts, with synthetic graph fixtures; no production parser or complete style support is implemented |
| JSON | validate a declared source schema/version; map semantic fields explicitly; distinguish native Corpora JSON from arbitrary JSON; preserve unknown optional source fields in namespaced extensions where possible |
| Plain/other documents | one work/edition/revision/stream is enough; record encoding, newline handling and extraction/OCR choices; add pages/paragraphs only when source evidence supports them |

The intended scripture source format is **USX**, clarified by the user after a
voice transcription error. Its adapter mapping is specified separately from the
Corpora XML representation below. Corpora owns the target contract; USX remains
a source representation, alongside TEI and other formats.

## JSON, XML and database representations

JSON serializes the graph as the schema-defined bundle. Object member order is
insignificant; array order and string content are significant. No inherited
whitespace, separators or source-specific object behavior exists.

Corpora XML 0.4.0 is a typed value encoding of the same logical JSON graph. Root
is `{urn:corpora:corpus-document:xml:0.4.0}document`. It contains exactly one
value element. `object` contains ordered `member` elements with unique `name`
attributes (Base64 of each JSON key in UTF-8) and one value each; `array` contains values in array order. Scalar
values are `string`, `number`, `boolean` or `null`. Strings use Base64 of UTF-8
bytes so XML newline normalization and XML-forbidden control characters cannot
change logical text. Number content is a finite JSON number token; boolean is
`true` or `false`; null is empty. Mixed content is forbidden.
No DTD, entity declarations or external entity access is permitted. Object member
order need not survive; values, names and arrays MUST. This deliberately simple
encoding avoids claiming that arbitrary XML markup can be reconstructed.
`xml_codec.py` supplies the reference conversion. After decoding, run the same
JSON schema and graph checks. An XSD and ergonomic XML vocabulary are future
options; neither is necessary to conform to this typed representation.

| Relational mapping | Constraint / behavior |
| --- | --- |
| entities and bibliographic tables | globally unique IDs; work→edition FK; collection_members(collection_id, order, work_id, edition_id); no work owner-corpus FK |
| revisions and text_streams | unique(edition_id, sequence); unique(revision_id, order); transactionally freeze revisions and dependent rows; store original UTF-8 text without normalization |
| anchors/anchor_segments and nodes | anchor_segments(anchor_id, segment_order, stream_id, start_scalar, end_scalar); enforce revision FK consistency and scalar bounds; nodes reference shared anchors or an exclusive position_stream_id/position_scalar boundary |
| structures/structure_members | unique(revision_id, name); unique(structure_id, node_id); unique(structure_id, parent_id, order), including null-parent uniqueness; validate acyclicity transactionally |
| profiles, annotations, relations, citations and provenance | immutable profile IDs; contribution/annotation attribution FKs; endpoint join tables for hyperedges; scheme entries keyed by scheme_id/key with unique order; assets/import reports; JSON value columns for features/extensions and rich blocks |

Do not use database byte length or UTF-16 length as scalar length. Null sibling
parents need an explicit database uniqueness strategy. Cross-revision invariants
and cycles require transaction validation beyond ordinary FKs. Database-generated
routes and citations are derived views; round-trip export must reconstruct the
same logical records, ordering and unknown extensions. This is mapping guidance,
not a migration or claim that current Supabase tables conform.

## Evolution

0.4.0 is a fresh unpublished contract, with no consumer compatibility requirement.
It is versioned now for future evolution. Review can replace draft design freely;
a changed draft distribution gets a new version and immutable manifest. After
publication, incompatible semantics or shape require a major version; additive
optional capabilities use a minor version; clarifications that do not change
accepted documents use a patch version. Consumers pin exact versions and reject
unsupported required capabilities. No dependency-driven version aliases or
legacy migration/deprecation machinery are introduced.
