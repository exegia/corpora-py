import pytest
from corpora_linking import Endpoint, PdfLocator, PdfPoint, PdfQuad
from test_epub import epub_bytes

from corpora_py.linking_cfi import (
    _dom,
    _package_path,
    _resource,
    make_epub_cfi_selection,
    retrieve_epub_cfi_selection,
)
from corpora_py.linking_html import retrieve_html_range, utf16_to_scalar
from corpora_py.linking_html_ranges import _stream, make_html_range
from corpora_py.linking_pdf import sha256_revision


def base(data, package):
    return Endpoint(
        work_id="essay",
        edition_id="e",
        package_id=package,
        revision=sha256_revision(data),
        document_id="asset",
    )


def test_epub_cfi_spans_inline_nodes_and_preserves_utf16_unicode():
    data = epub_bytes()
    _, root = _resource(data, _package_path(data), "first.xhtml")
    text, _ = _dom(root)
    for quote in ("😀", "John 3:16", "é John"):
        start = text.index(quote)
        endpoint = make_epub_cfi_selection(
            data,
            base(data, "epub"),
            asset_id="epub",
            href="first.xhtml",
            start=start,
            end=start + len(quote),
        )
        assert retrieve_epub_cfi_selection(data, endpoint) == quote
        assert endpoint.locators[0].cfi.startswith("epubcfi(/6/4!")
    altered = endpoint.locators[0].model_copy(
        update={"cfi": endpoint.locators[0].cfi.replace("/6/4!", "/6/2!")}
    )
    with pytest.raises(ValueError, match="href mismatch"):
        retrieve_epub_cfi_selection(data, endpoint.model_copy(update={"locators": (altered,)}))
    with pytest.raises(ValueError, match="pinned"):
        retrieve_epub_cfi_selection(data + b"changed", endpoint)


def test_html_range_crosses_inline_nodes_and_translates_browser_utf16():
    data = b"<html><head></head><body><p>\xf0\x9f\x98\x80 Compare John <em>3:16</em>.</p></body></html>"
    text, spans = _stream(data)
    first, second = spans[:2]
    endpoint = make_html_range(
        data,
        base(data, "html"),
        asset_id="html",
        start_path=first[0],
        start_utf16=3,
        end_path=second[0],
        end_utf16=4,
    )
    assert retrieve_html_range(data, endpoint) == "Compare John 3:16"
    assert utf16_to_scalar("😀x", 2) == 1
    with pytest.raises(ValueError, match="surrogate"):
        utf16_to_scalar("😀x", 1)
    altered = endpoint.locators[0].model_copy(update={"end_offset": 3})
    with pytest.raises(ValueError, match="bounds"):
        retrieve_html_range(data, endpoint.model_copy(update={"locators": (altered,)}))


def test_pymupdf_real_rotation_crop_quads_and_exact_retrieval():
    pymupdf = pytest.importorskip("pymupdf")
    from corpora_py.linking_pymupdf import (
        _extract,
        extract_pymupdf_references_input,
        pdf_display_quad_to_native,
        retrieve_pdf_selection,
    )

    with pymupdf.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((70, 90), "John 3:16")
        page.set_cropbox(pymupdf.Rect(30, 20, 280, 190))
        page.set_rotation(90)
        data = document.tobytes()
    text, glyphs = _extract(data)
    converted = base(text.encode(), "text")
    conversion = extract_pymupdf_references_input(
        data, original=base(data, "pdf"), converted=converted, asset_id="pdf"
    )
    assert text == "John 3:16"
    for mapping in conversion.mappings:
        assert retrieve_pdf_selection(data, mapping.original) == mapping.converted.locators[0].exact
    with pymupdf.open(stream=data, filetype="pdf") as document:
        quad = glyphs[0][3]
        rotated = [
            pymupdf.Point(point.x, point.y) * document[0].rotation_matrix for point in quad.points
        ]
    transformed = pdf_display_quad_to_native(
        data, page=1, points=tuple((point.x, point.y) for point in rotated)
    )
    assert all(
        abs(a.x - b.x) < 1e-5 and abs(a.y - b.y) < 1e-5
        for a, b in zip(transformed.points, quad.points, strict=True)
    )
    with pytest.raises(ValueError, match="geometry"):
        original = conversion.mappings[0].original
        locator = original.locators[0].model_copy(update={"quads": (glyphs[-1][3],)})
        retrieve_pdf_selection(data, original.model_copy(update={"locators": (locator,)}))


def test_degenerate_pdf_geometry_is_rejected():
    with pytest.raises(ValueError):
        PdfQuad(points=(PdfPoint(x=0, y=0),) * 4)
    with pytest.raises(ValueError):
        PdfLocator(asset_id="pdf", page=1)


def test_browser_range_requires_full_dom_correspondence():
    from corpora_py.linking_html_ranges import make_browser_html_range

    data = b"<html><head></head><body><p>A <em>word</em>.</p></body></html>"
    _, spans = _stream(data)
    nodes = tuple((path, quote) for path, start, end, quote in spans)
    arguments = dict(
        asset_id="html", start_path=spans[0][0], start_utf16=0, end_path=spans[1][0], end_utf16=4
    )
    selected = make_browser_html_range(data, base(data, "html"), captured_nodes=nodes, **arguments)
    assert retrieve_html_range(data, selected) == "A word"
    with pytest.raises(ValueError, match="browser DOM"):
        make_browser_html_range(data, base(data, "html"), captured_nodes=nodes[:-1], **arguments)
