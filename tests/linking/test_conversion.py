import pytest
from corpora_linking import (
    BibleBook,
    BibleCitationDetector,
    ConversionMapping,
    Endpoint,
    EpubLocator,
    PdfLocator,
    PdfRectangle,
    TextLocator,
    TextSnapshot,
)

from corpora_py.linking_conversion import (
    ConversionInput,
    ConversionReferenceReport,
    detect_converted_references,
)


def fixture():
    text = "😀 Compare John 3:16."
    converted = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="converted",
        revision="converted:1",
        document_id="chapter",
    )
    selected = Endpoint.model_validate(
        {
            **converted.model_dump(),
            "locators": [TextLocator(stream_id="body", start=0, end=len(text), exact=text)],
        }
    )
    original = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="original",
        revision="original:1",
        document_id="file",
        locators=(
            PdfLocator(
                asset_id="pdf", page=2, rectangles=(PdfRectangle(x0=10, y0=20, x1=100, y1=40),)
            ),
        ),
    )
    mapping = ConversionMapping(
        original=original, converted=selected, method="fixture:extraction", fidelity="exact"
    )
    detector = BibleCitationDetector(
        books=(BibleBook(work_id="john", aliases=("John",)),),
        stream_id="body",
        profile="fixture",
        scheme_id="fixture",
        scheme_version="1",
        agent_id="converter",
    )
    return TextSnapshot(endpoint=converted, stream_id="body", text=text), mapping, detector


def test_pdf_evidence_and_reference_ids_survive_sidecar_roundtrip():
    snapshot, mapping, detector = fixture()
    report = detect_converted_references(
        ConversionInput(converted=snapshot, mappings=(mapping,)), detector
    )
    (record,) = report.references
    assert record.reference.source.locators[0].exact == "John 3:16"
    assert record.reference.source.locators[0].start == 10
    assert record.mappings == (mapping,)
    assert record.mappings[0].original.locators[0].page == 2
    assert record.diagnostics == ("mapping overlaps selection; native citation bounds unverified",)
    assert record.reference.resolution == "unresolved" and record.reference.review == "pending"
    assert ConversionReferenceReport.model_validate_json(report.model_dump_json()) == report


def test_epub_approximate_evidence_is_preserved_without_projection():
    snapshot, mapping, detector = fixture()
    original = Endpoint.model_validate(
        {
            **mapping.original.model_dump(),
            "locators": [
                EpubLocator(asset_id="epub", href="chapter.xhtml", cfi="epubcfi(/6/2!/4/2)")
            ],
        }
    )
    mapping = ConversionMapping(
        original=original, converted=mapping.converted, method="fixture:ocr", fidelity="approximate"
    )
    (record,) = detect_converted_references(
        ConversionInput(converted=snapshot, mappings=(mapping,)), detector
    ).references
    assert record.mappings[0].original == original
    assert "approximate original location evidence" in record.diagnostics


def test_missing_mappings_keep_reference_with_diagnostic():
    snapshot, _, detector = fixture()
    report = detect_converted_references(ConversionInput(converted=snapshot), detector)
    assert report.references[0].diagnostics == ("original location mapping unavailable",)


@pytest.mark.parametrize("field,value", [("revision", "converted:2"), ("document_id", "other")])
def test_other_scope_mapping_is_rejected(field, value):
    snapshot, mapping, _ = fixture()
    changed = Endpoint.model_validate({**mapping.converted.model_dump(), field: value})
    with pytest.raises(ValueError, match="another converted"):
        ConversionInput(
            converted=snapshot,
            mappings=(
                ConversionMapping(
                    original=mapping.original, converted=changed, method="fixture", fidelity="exact"
                ),
            ),
        )


def test_stale_mapping_and_detector_anchor_rejected():
    snapshot, mapping, detector = fixture()
    changed = TextSnapshot(
        endpoint=snapshot.endpoint, stream_id="body", text="x" * len(snapshot.text)
    )
    with pytest.raises(ValueError, match="stale converted"):
        ConversionInput(converted=changed, mappings=(mapping,))

    class StaleDetector:
        def detect(self, source, text):
            return detector.detect(source, " " + text)

    with pytest.raises(ValueError, match="stale converted"):
        detect_converted_references(ConversionInput(converted=snapshot), StaleDetector())


def test_no_match_still_retains_original_conversion_mappings():
    snapshot, mapping, detector = fixture()
    detector = type(detector).model_validate(
        {**detector.model_dump(), "books": [BibleBook(work_id="genesis", aliases=("Genesis",))]}
    )
    report = detect_converted_references(
        ConversionInput(converted=snapshot, mappings=(mapping,)), detector
    )
    assert not report.references and report.conversion.mappings == (mapping,)


def test_conversion_example():
    import runpy
    from pathlib import Path

    example = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "packages/linking/examples/converted_link.py")
    )
    report = example["converted_link"]()
    assert report.references[0].reference.source.locators[0].exact == "John 3:16"
    assert report.references[0].mappings[0].fidelity == "unverified"
