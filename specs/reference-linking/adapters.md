---
title: Source adapter investigation
description: Candidate format adapters and exact-location constraints.
tags: [references, adapters]
---

# Candidate adapters

PyMuPDF `Page.get_text("rawdict")` offers character boxes; quads and page rotation
matrices can retain rotated selections. Convert its zero-based page indices to
core one-based pages and explicitly transform CropBox origins and rotation.
Its AGPL/commercial licensing requires an extraction/distribution decision.
See https://pymupdf.readthedocs.io/en/latest/textpage.html .

pdfplumber exposes character geometry and one-based page numbers, with top/bottom
coordinates as well as PDF bottom-origin y values. Store the selected coordinate
transform and extraction order; neither tool guarantees OCR or reading-order fidelity.
See https://github.com/jsvine/pdfplumber .

EbookLib provides EPUB archive resources and spine order, but is not an EPUB CFI
resolver. A separate DOM-aware adapter must validate CFI paths/assertions against
the pinned asset, translate UTF-16 text offsets into Unicode scalar offsets, and
retain mappings through DOM text joins and normalization. Do not calculate CFI
from flattened text positions. See https://docs.sourcefabric.org/projects/ebooklib/en/latest/ .

Use W3C Web Annotation and Readium Locators as selector design references, not
claims of wire conformance. Future fixtures must include PDF crop/rotation/OCR,
EPUB split DOM nodes/astral Unicode, ambiguous quotes and changed assets. Heavy
libraries stay outside the core; vector discovery never verifies a selection.

# Implemented PDF slice

The optional umbrella `linking-pdf` extra provides pdfplumber; the core dependency
set is unchanged. `corpora_py.linking_pdf` verifies original PDF bytes and converted
UTF-8 stream digests and emits approximate word-rectangle mappings. Extraction
orders words geometrically, inserts spaces between words and U+000C between pages,
keeps blank pages, and disables ligature expansion. This is a separate pinned
stream from existing pypdf/TF extraction, never an interchangeable revision.

The initial coordinate subset requires uncropped zero-origin unrotated pages and
upright glyphs; unsupported transforms reject instead of mislabeling coordinates.
Actual PDF fixtures cover citation detection, rectangles, blank pages, checksum
mismatch, crop and rotation rejection. Native citation projection, OCR, multi-column
reading-order guarantees and supported crop/rotation transforms remain pending.

# Implemented EPUB slice

The umbrella EbookLib/lxml adapter reads raw item content (not rewritten
`get_content()`), orders linear XHTML resources by spine, verifies archive/text
digests and emits approximate resource-range mappings. A new optional typed
`EpubResourceLocator` records asset/href without fabricating CFI precision.
DOM text/tails remain verbatim; `br` becomes LF, script/style/comment content is
excluded, and resources join with U+000C, retaining empty resources. XML uses no
external entity resolution and rejects DOCTYPE declarations. This is an extraction
stream, not browser-rendered text, and CSS visibility is not evaluated.

Fixtures include manifest/spine order differences, split inline citations, astral
and decomposed Unicode, empty resources, missing/repeated spine entries, digest
mismatches and XML validation. Native CFI path/assertion and UTF-16 offset handling
remain explicit future work; resource mappings confer no exact passage authority.
