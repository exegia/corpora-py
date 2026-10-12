"""Typed manifest contract for the multi-document development profile."""

from typing import Annotated, Literal

from corpora_linking import Endpoint
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from ..parsers.schema import SourceFormat

Name = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackageIdentity(Contract):
    work_id: Name
    edition_id: Name
    package_id: Name


class Source(Contract):
    filename: Name
    format: SourceFormat
    revision: Digest
    evidence: Name | None = None


class DocumentSource(Contract):
    path: Name
    fragment: str = ""
    start_event: Annotated[StrictInt, Field(ge=0)] | None = None
    end_event: Annotated[StrictInt, Field(gt=0)] | None = None
    page_number: Annotated[StrictInt, Field(gt=0)] | None = None
    page_label: str | None = None

    @model_validator(mode="after")
    def bounds(self):
        if (self.start_event is None) != (self.end_event is None) or (
            self.start_event is not None and self.end_event <= self.start_event
        ):
            raise ValueError("Source ranges require ordered start/end events")
        return self


class DocumentEntry(Contract):
    id: Name
    path: Name
    tree: Name
    snapshot: Name
    identity: Endpoint
    characters: Annotated[StrictInt, Field(ge=0)]
    label: str
    role: Name
    source: DocumentSource
    linear: StrictBool
    in_spine: StrictBool


class NavigationTarget(Contract):
    document_id: Name
    fragment: str


class NavigationEntry(Contract):
    label: str
    source_href: str
    role: str
    children: list["NavigationEntry"]
    source_path: str | None = None
    fragment: str = ""
    external_href: str | None = None
    target: NavigationTarget | None = None


class Stream(Contract):
    id: Literal["cusx-itertext/v1"]
    offset_unit: Literal["unicode-scalar"]
    normalization: Literal["preserve"]


class PackageManifest(Contract):
    format: Literal["corpora-cusx-package/0.2.0"]
    name: str
    description: str
    category: str
    created_by: str | None
    identity: PackageIdentity
    source: Source
    stream: Stream
    documents: Annotated[list[DocumentEntry], Field(min_length=1)]
    reading_order: Annotated[list[Name], Field(min_length=1)]
    supplementary: list[Name]
    navigation: dict[str, list[NavigationEntry]]
    assets: list[Name]
    diagnostics: list[str]
    files: dict[Name, Digest]
