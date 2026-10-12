"""Optional pdfplumber extraction; deliberately bounded geometry support."""

import hashlib
import io

from corpora_linking import (
    ConversionMapping,
    Endpoint,
    PdfLocator,
    PdfRectangle,
    TextLocator,
    TextSnapshot,
)

from .linking_conversion import ConversionInput


def sha256_revision(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def extract_pdf_references_input(
    data: bytes,
    *,
    original: Endpoint,
    converted: Endpoint,
    asset_id: str,
    stream_id: str = "body",
) -> ConversionInput:
    """Extract words separated by spaces; pages separated by U+000C.

    Both endpoints describe whole documents. Original revision is SHA-256 of PDF
    bytes; converted revision is SHA-256 of the emitted UTF-8 stream. No Unicode
    normalization, OCR, layout fidelity or exact native citation bounds are claimed.
    Only zero-origin, uncropped, unrotated pages and upright glyphs are supported.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError("install corpora-py[linking-pdf] for PDF extraction") from exc
    if original.locators or converted.locators:
        raise ValueError("extraction endpoints must describe whole documents")
    if original.revision != sha256_revision(data):
        raise ValueError("original PDF checksum mismatch")
    if original.work_id != converted.work_id or original.edition_id != converted.edition_id:
        raise ValueError("conversion must preserve supplied work and edition identity")
    text = ""
    spans = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for index, page in enumerate(pdf.pages):
            if (
                page.rotation
                or tuple(page.cropbox) != tuple(page.mediabox)
                or any(float(v) != 0 for v in page.mediabox[:2])
            ):
                raise ValueError("unsupported PDF rotation, crop or page origin")
            if any(not char.get("upright", False) for char in page.chars):
                raise ValueError("unsupported rotated PDF glyph")
            if index:
                text += "\f"
            words = page.extract_words(
                return_chars=True, expand_ligatures=False, use_text_flow=False
            )
            for word_index, word in enumerate(words):
                if word_index:
                    text += " "
                quote = word["text"]
                if not quote or quote != "".join(char["text"] for char in word["chars"]):
                    raise ValueError("unsupported PDF word/character correspondence")
                rectangle = PdfRectangle(
                    x0=word["x0"], y0=word["top"], x1=word["x1"], y1=word["bottom"]
                )
                if rectangle.x1 > page.width or rectangle.y1 > page.height:
                    raise ValueError("PDF word geometry exceeds page bounds")
                start = len(text)
                text += quote
                spans.append((start, len(text), quote, page.page_number, rectangle))
    if converted.revision != sha256_revision(text.encode("utf-8")):
        raise ValueError("converted text checksum mismatch")
    mappings = []
    for start, end, quote, page_number, rectangle in spans:
        native = Endpoint.model_validate(
            {
                **original.model_dump(),
                "locators": [
                    PdfLocator(asset_id=asset_id, page=page_number, rectangles=(rectangle,))
                ],
            }
        )
        selection = Endpoint.model_validate(
            {
                **converted.model_dump(),
                "locators": [TextLocator(stream_id=stream_id, start=start, end=end, exact=quote)],
            }
        )
        mappings.append(
            ConversionMapping(
                original=native,
                converted=selection,
                method="pdfplumber:words-space-pages-formfeed/v1",
                fidelity="approximate",
            )
        )
    return ConversionInput(
        converted=TextSnapshot(endpoint=converted, stream_id=stream_id, text=text),
        mappings=tuple(mappings),
    )
