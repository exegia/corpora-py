"""Optional PyMuPDF glyph-quads, crop/rotation transforms and exact pinned retrieval."""

from corpora_linking import (
    ConversionMapping,
    Endpoint,
    PdfLocator,
    PdfPoint,
    PdfQuad,
    TextLocator,
    TextSnapshot,
    verify_text_anchor,
)

from .linking_conversion import ConversionInput
from .linking_pdf import sha256_revision


def _extract(data: bytes):
    import pymupdf

    parts, glyphs = [], []
    offset = 0
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("encrypted PDF requires an explicit decryption adapter")
        for page_index, page in enumerate(document):
            if page_index:
                parts.append("\f")
                offset += 1
            first_line = True
            for block in page.get_text("rawdict", sort=False)["blocks"]:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    if not first_line:
                        parts.append("\n")
                        offset += 1
                    first_line = False
                    for span in line["spans"]:
                        for char in span["chars"]:
                            quote = char["c"]
                            if not quote:
                                continue
                            quad = pymupdf.recover_char_quad(line["dir"], span, char)
                            points = (quad.ul, quad.ur, quad.lr, quad.ll)
                            if any(
                                p.x < 0
                                or p.y < 0
                                or p.x > page.cropbox.width
                                or p.y > page.cropbox.height
                                for p in points
                            ):
                                raise ValueError("PDF glyph quad lies outside unrotated CropBox")
                            value = PdfQuad.model_validate(
                                {"points": tuple(PdfPoint(x=p.x, y=p.y) for p in points)}
                            )
                            parts.append(quote)
                            glyphs.append((offset, offset + len(quote), page_index + 1, value))
                            offset += len(quote)
    return "".join(parts), glyphs


def pdf_display_quad_to_native(
    data: bytes, *, page: int, points: tuple[tuple[float, float], ...]
) -> PdfQuad:
    """Viewer coordinates: rotated CropBox, top-left points, one-based page."""
    import pymupdf

    if len(points) != 4 or type(page) is not int or page < 1:
        raise ValueError("four points and a one-based page are required")
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if page > len(document):
            raise ValueError("PDF page unavailable")
        item = document[page - 1]
        transformed = [pymupdf.Point(*point) * item.derotation_matrix for point in points]
        if any(
            p.x < 0 or p.y < 0 or p.x > item.cropbox.width or p.y > item.cropbox.height
            for p in transformed
        ):
            raise ValueError("PDF quad exceeds CropBox")
        return PdfQuad.model_validate(
            {"points": tuple(PdfPoint(x=p.x, y=p.y) for p in transformed)}
        )


def extract_pymupdf_references_input(
    data: bytes, *, original: Endpoint, converted: Endpoint, asset_id: str, stream_id: str = "body"
) -> ConversionInput:
    if original.locators or converted.locators or original.revision != sha256_revision(data):
        raise ValueError("PDF extraction requires a pinned whole original asset")
    if (original.work_id, original.edition_id) != (converted.work_id, converted.edition_id):
        raise ValueError("conversion must preserve work and edition")
    text, glyphs = _extract(data)
    if converted.revision != sha256_revision(text.encode()):
        raise ValueError("converted PDF text checksum mismatch")
    mappings = []
    for start, end, page, quad in glyphs:
        quote = text[start:end]
        native_text = TextLocator(stream_id="pymupdf-body", start=start, end=end, exact=quote)
        native = Endpoint.model_validate(
            {
                **original.model_dump(),
                "locators": [
                    PdfLocator(asset_id=asset_id, page=page, quads=(quad,), text=native_text)
                ],
            }
        )
        selected = Endpoint.model_validate(
            {
                **converted.model_dump(),
                "locators": [TextLocator(stream_id=stream_id, start=start, end=end, exact=quote)],
            }
        )
        mappings.append(
            ConversionMapping(
                original=native,
                converted=selected,
                method="pymupdf:rawdict-glyph-quads/v1",
                fidelity="exact",
            )
        )
    return ConversionInput(
        converted=TextSnapshot(endpoint=converted, stream_id=stream_id, text=text),
        mappings=tuple(mappings),
    )


def retrieve_pdf_selection(data: bytes, endpoint: Endpoint) -> str:
    if endpoint.revision != sha256_revision(data):
        raise ValueError("stale PDF asset")
    if not endpoint.locators or any(
        not isinstance(locator, PdfLocator) for locator in endpoint.locators
    ):
        raise ValueError("PDF selection requires native PDF locators")
    text, glyphs = _extract(data)
    results = []
    previous_end = -1
    for locator in endpoint.locators:
        assert isinstance(locator, PdfLocator)
        selector = locator.text
        if (
            selector is None
            or selector.stream_id != "pymupdf-body"
            or selector.normalization != "preserve"
        ):
            raise ValueError("PDF retrieval requires an exact native text selector")
        if selector.start < previous_end:
            raise ValueError("PDF fragments must be ordered and nonoverlapping")
        expected = tuple(
            quad
            for start, end, page, quad in glyphs
            if page == locator.page and selector.start <= start and end <= selector.end
        )
        covered = [item for item in glyphs if selector.start < item[1] and item[0] < selector.end]
        if (
            not expected
            or any(item[2] != locator.page for item in covered)
            or locator.quads != expected
            or locator.rectangles
        ):
            raise ValueError("PDF geometry does not match the selected glyphs")
        if (
            verify_text_anchor(
                selector,
                text,
                expected_revision=endpoint.revision or "",
                actual_revision=sha256_revision(data),
            )
            != "valid"
        ):
            raise ValueError("stale PDF quote/context")
        results.append(text[selector.start : selector.end])
        previous_end = selector.end
    return "\f".join(results)
