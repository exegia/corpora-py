"""Opt-in conversion sidecars, outside the reusable linking core."""

from typing import Self

from corpora_linking import (
    ConversionMapping,
    Detector,
    Endpoint,
    Reference,
    TextLocator,
    TextSnapshot,
    verify_text_anchor,
)
from corpora_linking.models import Value
from pydantic import model_validator


def _validate_selection(endpoint: Endpoint, snapshot: TextSnapshot) -> TextLocator:
    base = Endpoint.model_validate({**endpoint.model_dump(), "locators": []})
    if base != snapshot.endpoint or len(endpoint.locators) != 1:
        raise ValueError("selection belongs to another converted stream or revision")
    locator = endpoint.locators[0]
    if not isinstance(locator, TextLocator) or locator.stream_id != snapshot.stream_id:
        raise ValueError("selection requires the converted text stream")
    if (
        verify_text_anchor(
            locator,
            snapshot.text,
            expected_revision=endpoint.revision or "",
            actual_revision=snapshot.endpoint.revision or "",
        )
        != "valid"
    ):
        raise ValueError("stale converted selection")
    return locator


class ConversionInput(Value):
    """One converted stream and supplied original-file correspondence evidence."""

    converted: TextSnapshot
    mappings: tuple[ConversionMapping, ...] = ()

    @model_validator(mode="after")
    def validate_mappings(self) -> Self:
        for mapping in self.mappings:
            _validate_selection(mapping.converted, self.converted)
            if not mapping.original.locators:
                raise ValueError("original mapping must retain location evidence")
        return self


class ConvertedReference(Value):
    reference: Reference
    mappings: tuple[ConversionMapping, ...] = ()
    diagnostics: tuple[str, ...] = ()


class ConversionReferenceReport(Value):
    """Working sidecar; never an approval or XML publication operation."""

    conversion: ConversionInput
    references: tuple[ConvertedReference, ...]


def detect_converted_references(
    conversion: ConversionInput, detector: Detector
) -> ConversionReferenceReport:
    """Retain overlapping mappings without projecting native citation bounds.

    Providers verify original asset identity, page geometry and CFI themselves.
    """
    snapshot = conversion.converted
    records = []
    for reference in detector.detect(snapshot.endpoint, snapshot.text):
        reference = Reference.model_validate(reference.model_dump())
        locator = _validate_selection(reference.source, snapshot)
        mappings = tuple(
            m
            for m in conversion.mappings
            if isinstance(m.converted.locators[0], TextLocator)
            and m.converted.locators[0].start < locator.end
            and m.converted.locators[0].end > locator.start
        )
        diagnostics = []
        if not mappings:
            diagnostics.append("original location mapping unavailable")
        for mapping in mappings:
            if mapping.fidelity != "exact":
                diagnostics.append(f"{mapping.fidelity} original location evidence")
            if mapping.converted != reference.source:
                diagnostics.append("mapping overlaps selection; native citation bounds unverified")
        records.append(
            ConvertedReference(
                reference=reference,
                mappings=mappings,
                diagnostics=tuple(dict.fromkeys(diagnostics)),
            )
        )
    return ConversionReferenceReport(conversion=conversion, references=tuple(records))
