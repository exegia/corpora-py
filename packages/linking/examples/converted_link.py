"""Corpora integration example; requires corpora-py, not only corpora-linking."""

from corpora_linking import (
    BibleBook,
    BibleCitationDetector,
    ConversionMapping,
    Endpoint,
    EpubLocator,
    TextLocator,
    TextSnapshot,
)

from corpora_py.linking_conversion import ConversionInput, detect_converted_references


def converted_link():
    text = "Compare John 3:16."
    base = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="converted",
        revision="converted:1",
        document_id="chapter",
    )
    original = Endpoint(
        work_id="essay",
        edition_id="e",
        package_id="original",
        revision="original:1",
        document_id="chapter.xhtml",
        locators=(EpubLocator(asset_id="epub", href="chapter.xhtml", cfi="epubcfi(/6/2!/4/2)"),),
    )
    block = Endpoint.model_validate(
        {
            **base.model_dump(),
            "locators": [TextLocator(stream_id="body", start=0, end=len(text), exact=text)],
        }
    )
    conversion = ConversionInput(
        converted=TextSnapshot(endpoint=base, stream_id="body", text=text),
        mappings=(
            ConversionMapping(
                original=original, converted=block, method="fixture:epub", fidelity="unverified"
            ),
        ),
    )
    detector = BibleCitationDetector(
        books=(BibleBook(work_id="john", aliases=("John",)),),
        stream_id="body",
        profile="fixture",
        scheme_id="fixture",
        scheme_version="1",
        agent_id="converter",
    )
    return detect_converted_references(conversion, detector)


if __name__ == "__main__":
    print(converted_link().model_dump_json(indent=2))
