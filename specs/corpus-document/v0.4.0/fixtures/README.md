# Conformance fixtures

All examples are synthetic and deliberately small. `index.json` exhaustively
lists JSON documents, with null for valid cases or the exact required error
prefix for invalid cases. The executable checker also validates every schema
and round-trips every fixture through JSON and Corpora XML.

| Scenario | Valid mechanics | Invalid counterpart |
| --- | --- | --- |
| Bible numbering | reusable work in two ordered collections; Psalm 51 / 50 schemes, title and skipped/suffixed keys; second translation revision; 2×2 attributed alignment; commentary; all four resolution outcomes | duplicate citation key, cross-revision anchor, invalid predecessor |
| Quran edition | Arabic scalar text; explicit recension identity; edition-scoped surah/verse string keys and inclusive range | requested scheme version unavailable while claiming resolved |
| Paginated book | paragraph crosses independent page anchors; separate paragraph/page structures | parent cycle |
| Single page / minimal document | five scalar values including emoji and combining mark; optional opaque extension; minimal variant omits all nodes and anchors | offset beyond scalar length |
| Text-Fabric discontinuity | one clause covers nonadjacent spans; namespaced tense, source node ID and slot extension; attributed import report | overlapping segments within one anchor |

USX projection fixtures add synthetic scripture and peripheral graphs with
matching `.usx` source assets. Scripture demonstrates a bridged verse and
quotation spanning poetry lines, introduction, character style and positioned
footnote. Peripheral content demonstrates a divided front-matter work, table
cells, sidebar and unverified reference metadata. Four invalid fixtures cover
position bounds, shape, stream linkage and required capability. The focused test
verifies asset checksums and XML well-formedness, not upstream USX validity or a
parser transformation. See [USX assessment](../usx-adapter.md).

Additional invalid cases cover unsupported required capability, dangling work,
unknown schema field and duplicate identity. Synthetic slot/number mappings are
illustrations, not verified exports from upstream datasets. The TF report says
which feature inventory was omitted. External citation existence stays unverified
unless its bundle is loaded; the focused tests cover both loaded/missing targets.
