import pytest
from corpora_linking import (
    BibleBook,
    BibleCitationDetector,
    Endpoint,
    HtmlTextLocator,
    TextLocator,
)

from corpora_py.linking_conversion import ConversionReferenceReport, detect_converted_references
from corpora_py.linking_html import (
    extract_html_references_input,
    html_parser_version,
    retrieve_html_selection,
)
from corpora_py.linking_pdf import sha256_revision

DATA = "<html><head><title>Ignore</title></head><body><p>😀 é John <em>3:16</em> &amp; more.</p><!--ignored--><script>John 1:1</script><p>Repeated</p><p>Repeated</p><br>tail</body></html>".encode()
TEXT = "😀 é John 3:16 & more.\nRepeated\nRepeated\n\ntail"


def endpoints(data=DATA, text=TEXT):
    return (
        Endpoint(
            work_id="essay",
            edition_id="e",
            package_id="html",
            revision=sha256_revision(data),
            document_id="file",
        ),
        Endpoint(
            work_id="essay",
            edition_id="e",
            package_id="text",
            revision=sha256_revision(text.encode()),
            document_id="file",
        ),
    )


def fixture():
    original, converted = endpoints()
    return extract_html_references_input(
        DATA, original=original, converted=converted, asset_id="html"
    )


def test_html_unicode_entities_inline_citations_and_native_retrieval():
    conversion = fixture()
    assert conversion.converted.text == TEXT
    for mapping in conversion.mappings:
        assert (
            retrieve_html_selection(DATA, mapping.original) == mapping.converted.locators[0].exact
        )
    detector = BibleCitationDetector(
        books=(BibleBook(work_id="john", aliases=("John",)),),
        stream_id="body",
        profile="fixture",
        scheme_id="fixture",
        scheme_version="1",
        agent_id="test",
    )
    report = detect_converted_references(conversion, detector)
    (record,) = report.references
    assert record.reference.source.locators[0].start == TEXT.index("John")
    assert record.reference.source.locators[0].exact == "John 3:16"
    assert len(record.mappings) == 2
    assert record.reference.review == "pending"
    assert ConversionReferenceReport.model_validate_json(report.model_dump_json()) == report


def test_repeated_quotes_use_distinct_paths_and_never_relocate():
    conversion = fixture()
    repeated = [m for m in conversion.mappings if m.converted.locators[0].exact == "Repeated"]
    assert len(repeated) == 2
    assert repeated[0].original.locators[0].node_path != repeated[1].original.locators[0].node_path
    native = repeated[0].original
    with pytest.raises(ValueError, match="stale HTML asset"):
        retrieve_html_selection(DATA.replace(b"Repeated", b"Changed!", 1), native)
    locator = native.locators[0]
    wrong = HtmlTextLocator(
        asset_id="html",
        parser_version=html_parser_version(),
        node_path=locator.node_path,
        text=TextLocator(stream_id="dom-node", start=0, end=8, exact="Changed!"),
    )
    with pytest.raises(ValueError, match="stale HTML text"):
        retrieve_html_selection(
            DATA, Endpoint.model_validate({**native.model_dump(), "locators": [wrong]})
        )


def test_wrong_path_and_non_text_nodes_reject():
    base, _ = endpoints()
    for path in ((99,), (0,)):
        locator = HtmlTextLocator(
            asset_id="html",
            parser_version=html_parser_version(),
            node_path=path,
            text=TextLocator(stream_id="dom-node", start=0, end=1, exact="x"),
        )
        with pytest.raises(ValueError):
            retrieve_html_selection(
                DATA, Endpoint.model_validate({**base.model_dump(), "locators": [locator]})
            )


def test_digests_and_invalid_utf8_reject():
    original, converted = endpoints()
    with pytest.raises(ValueError, match="original HTML checksum"):
        extract_html_references_input(
            DATA + b" ", original=original, converted=converted, asset_id="html"
        )
    wrong = Endpoint.model_validate({**converted.model_dump(), "revision": "sha256:wrong"})
    with pytest.raises(ValueError, match="converted text checksum"):
        extract_html_references_input(DATA, original=original, converted=wrong, asset_id="html")
    bad = b"\xff"
    original, converted = endpoints(data=bad)
    with pytest.raises(UnicodeDecodeError):
        extract_html_references_input(bad, original=original, converted=converted, asset_id="html")


def test_fragments_empty_content_and_block_boundaries():
    for data, text in (
        (b"<p>John</p><p>3:16</p>", "John\n3:16\n"),
        (b"<!DOCTYPE html><script>hidden</script>", ""),
        (b"", ""),
    ):
        original, converted = endpoints(data=data, text=text)
        report = extract_html_references_input(
            data, original=original, converted=converted, asset_id="html"
        )
        assert report.converted.text == text


def test_partial_manual_selection_and_parser_version_validation():
    conversion = fixture()
    native = next(
        m.original for m in conversion.mappings if m.converted.locators[0].exact == "Repeated"
    )
    locator = native.locators[0]
    partial = HtmlTextLocator(
        asset_id=locator.asset_id,
        parser_version=locator.parser_version,
        node_path=locator.node_path,
        text=TextLocator(
            stream_id="dom-node", start=2, end=6, exact="peat", prefix="Re", suffix="ed"
        ),
    )
    selected = Endpoint.model_validate({**native.model_dump(), "locators": [partial]})
    assert retrieve_html_selection(DATA, selected) == "peat"
    stale = HtmlTextLocator.model_validate({**partial.model_dump(), "parser_version": "old-parser"})
    with pytest.raises(ValueError, match="stale HTML parser"):
        retrieve_html_selection(
            DATA, Endpoint.model_validate({**native.model_dump(), "locators": [stale]})
        )
