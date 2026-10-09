# Compressed C-USX document package

Status: development profile `corpora-cusx-package/0.1.0`, introduced by this
conversion change. This profile is separate from the draft corpus-document
v0.4 graph contract and the existing Text-Fabric `.corpus` archive contract.
Neither contract is replaced or claimed as implemented by this projection.

## Artifact and conversion

`.cusx` is a ZIP with DEFLATE compression. `document.usx` inside it is UTF-8
extended USX XML; a raw XML file is not the compressed package. The exact
inventory is:

| Member | Purpose |
| --- | --- |
| `manifest.json` | Profile, display metadata, local document identity, source digest, stream conventions and member hashes |
| `document.usx` | Parsed document projected into an unnamespaced `usx` root and namespaced Corpora units |
| `document.json` | The shared parser's complete Document/Unit/Token output, retained without a Text-Fabric compile |
| `snapshot.json` | Public linking TextSnapshot, pinning document identity, XML revision and exact converted text |
| `references.json` | Empty in this conversion profile; conversion does not claim reviewed reference publication |
| `mappings.json` | Empty mapping inventory with explicit missing-native-evidence diagnostic |

The XML uses `urn:corpora:usx-extension:0.1` and advertises the package profile.
`cx:unit` preserves source unit type, source-scoped ID, label and attributes;
its token text appears in `para style="p"` elements. This is a general-document
parser projection, not official USX scripture conformance: no book codes,
canonical verses or intellectual-work catalog identities are inferred.

The existing parsers handle individual EPUB, HTML, XML, TEI, PDF and plain-text
sources. Every PDF page must contain extractable text; a blank/unextractable
page rejects the whole conversion instead of being silently omitted. OCR,
reading-order verification and the full draft PDF acceptance policy are not
implemented by this projection. Dataset ZIPs use the existing corpus path.

The parser tree may already have changed source whitespace or structure. The
package preserves that parsed tree, not native-file text or layout fidelity.
Its source hash identifies the supplied bytes, but is not an original-location
mapping. Original files are not included. Unknown native location mappings stay
absent, rather than receiving invented paragraph IDs, page rectangles or CFIs.

## Identity and offsets

Conversion allocates local work/edition/package UUIDs; they require catalog
reconciliation before being treated as shared intellectual identities. A rerun
is a new local package, not evidence that two works are different or identical.
`document_id` is `document.usx`; its revision is the SHA-256 of the exact XML
bytes. The original upload gets its own byte digest in source metadata.

`cusx-itertext/v1` counts Unicode scalars in XML text and tails in document
order. Normalization is `preserve`. Leaf token-bearing units receive an explicit
two-newline separator in their XML tails. Those separators are converted text,
not claimed original offsets. Snapshot text must exactly equal this XML stream;
the existing reference anchoring helper reads the same stream. Selectors use
zero-based half-open bounds and exact quotes/context against this pinned stream.

## API and example app

`POST /convert` accepts `output_format=cusx` in the existing multipart request.
Omitting it retains `corpus` for compatibility. Unsupported output formats and
C-USX requests for dataset ZIPs fail before creating a job.

The example app explicitly requests C-USX for individual documents and corpus
for Text-Fabric/TEI dataset ZIPs. Existing status polling, WebSocket fallback,
download, retry and manual publication behavior remain the transport. The save
dialog uses the returned suffix. `/validate` dispatches C-USX packages to the
profile validator rather than loading them as Text-Fabric.

`POST /storage` still receives the succeeded job ID. It uses the existing
Hugging Face repo/bucket settings, authentication and upload methods; C-USX
filenames are preserved, and both archive types appear in storage listings.
Nothing is uploaded automatically. No live bucket, Supabase schema, credentials
or deployment settings are changed by this feature.

Persistent jobs keep the existing metadata columns: the result key carries the
`.cusx` suffix, which remains correct after another process materializes it.
Snapshots preserve that suffix as well.

## Validation and consumer limits

The validator checks exact membership, duplicate names, an uncompressed size
limit, member hashes, parsed-tree/XML correspondence, typed snapshot identity,
XML revision and exact stream text. Entity declarations are refused. Corrupt or
unsupported packages do not pass conversion validation. This checks this scoped
profile, not upstream USX or corpus-document graph conformance.

Metadata can be read from `manifest.json`. Text-Fabric index, graph queries,
annotation editing and legacy manifest mutation are not C-USX reader features;
graph queries explicitly reject these packages. A C-USX reader should consume
the XML/tree and snapshot, rather than pretend its units are Text-Fabric nodes.
Building that reader, authoritative native mappings, automatic citation sidecars,
reviewed reference embedding and package import/synchronization is further work.
The existing publication authority and stable reference IDs remain the basis
for that work; conversion alone never grants review or publication approval.
