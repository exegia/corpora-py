import io
import zipfile

import pytest
from corpora_linking import BibleBook, BibleCitationDetector, Endpoint, EpubResourceLocator

from corpora_py.linking_conversion import ConversionReferenceReport, detect_converted_references
from corpora_py.linking_epub import extract_epub_references_input
from corpora_py.linking_pdf import sha256_revision


def epub_bytes(*, missing=False, duplicate=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""",
        )
        refs = '<itemref idref="second"/><itemref idref="first"/><itemref idref="empty"/>'
        if missing:
            refs += '<itemref idref="missing"/>'
        if duplicate:
            refs += '<itemref idref="first"/>'
        archive.writestr(
            "EPUB/package.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">fixture</dc:identifier><dc:title>Fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="first" href="first.xhtml" media-type="application/xhtml+xml"/><item id="second" href="second.xhtml" media-type="application/xhtml+xml"/><item id="empty" href="empty.xhtml" media-type="application/xhtml+xml"/></manifest><spine>"""
            + refs
            + "</spine></package>",
        )
        for name, body in (
            ("first", "<p>😀 é John <em>3:16</em>.</p><script>John 1:1</script> tail"),
            ("second", "<p>Second<br/>line &amp; text.</p>"),
            ("empty", ""),
        ):
            archive.writestr(
                f"EPUB/{name}.xhtml",
                (
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ignore</title></head><body>'
                    + body
                    + "</body></html>"
                ).encode(),
            )
    return output.getvalue()


TEXT = "Second\nline & text.\f😀 é John 3:16. tail\f"


def endpoints(data):
    return (
        Endpoint(
            work_id="essay",
            edition_id="e",
            package_id="epub",
            revision=sha256_revision(data),
            document_id="file",
        ),
        Endpoint(
            work_id="essay",
            edition_id="e",
            package_id="text",
            revision=sha256_revision(TEXT.encode()),
            document_id="file",
        ),
    )


def test_real_epub_spine_unicode_and_resource_mappings():
    data = epub_bytes()
    original, converted = endpoints(data)
    conversion = extract_epub_references_input(
        data, original=original, converted=converted, asset_id="epub"
    )
    assert conversion.converted.text == TEXT
    assert [m.original.locators[0].href for m in conversion.mappings] == [
        "second.xhtml",
        "first.xhtml",
    ]
    assert isinstance(conversion.mappings[0].original.locators[0], EpubResourceLocator)
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
    assert record.reference.source.locators[0].exact == "John 3:16"
    assert record.reference.source.locators[0].start == TEXT.index("John")
    assert record.mappings[0].original.locators[0].href == "first.xhtml"
    assert record.mappings[0].fidelity == "approximate"
    assert ConversionReferenceReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    "changes,message",
    [({"missing": True}, "missing or unsupported"), ({"duplicate": True}, "repeated EPUB")],
)
def test_missing_or_repeated_spine_resource_rejected(changes, message):
    data = epub_bytes(**changes)
    original, converted = endpoints(data)
    with pytest.raises(ValueError, match=message):
        extract_epub_references_input(data, original=original, converted=converted, asset_id="epub")


def test_original_and_converted_digest_mismatches_rejected():
    data = epub_bytes()
    original, converted = endpoints(data)
    for field, message in (("original", "original EPUB"), ("converted", "converted text")):
        wrong = Endpoint.model_validate(
            {
                **(original if field == "original" else converted).model_dump(),
                "revision": "sha256:wrong",
            }
        )
        with pytest.raises(ValueError, match=message):
            extract_epub_references_input(
                data,
                original=wrong if field == "original" else original,
                converted=wrong if field == "converted" else converted,
                asset_id="epub",
            )


def test_xhtml_extraction_rejects_doctype_and_missing_body():
    from corpora_py.linking_epub import _body_text

    with pytest.raises(ValueError, match="DOCTYPE"):
        _body_text(
            b'<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><body>x</body></html>'
        )
    with pytest.raises(ValueError, match="one XHTML body"):
        _body_text(b'<html xmlns="http://www.w3.org/1999/xhtml"><head/></html>')


def test_verbatim_whitespace_and_inline_tails_are_not_normalized():
    from corpora_py.linking_epub import _body_text

    content = '<html xmlns="http://www.w3.org/1999/xhtml"><body>  é <b>😀</b> tail<!--ignored--> end<style>hidden</style> kept</body></html>'
    assert _body_text(content.encode()) == "  é 😀 tail end kept"
