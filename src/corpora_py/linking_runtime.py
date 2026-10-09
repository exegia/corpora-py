"""Configured resource authority and production linking service composition.

Inventory values come from a trusted server manifest/provider, never request bodies.
No schema provisioning, distribution, network lookup or implicit grants occur here.
"""

from typing import Literal
from uuid import UUID

import psycopg
from corpora_linking import (
    BibleBook,
    BibleCitationDetector,
    CatalogEntry,
    Endpoint,
    EpubLocator,
    HtmlRangeLocator,
    HtmlTextLocator,
    PassageEntry,
    PdfLocator,
    ResolutionResult,
    ScholarlyCitationRecognizer,
    SnapshotCatalog,
    SnapshotResolver,
    StructuralLocator,
    TextSnapshot,
)
from corpora_linking.models import NonEmpty, Value
from pydantic import ConfigDict, model_validator

from .linking_access import endpoint_scope
from .linking_postgres import PostgreSQLReferenceStore


class AssetRecord(Value):
    model_config = ConfigDict(
        extra="forbid", frozen=True, ser_json_bytes="base64", val_json_bytes="base64"
    )
    endpoint: Endpoint
    format: Literal["pdf", "epub", "html", "cusx"]
    data: bytes
    checksum: NonEmpty | None = None

    @model_validator(mode="after")
    def pinned(self) -> "AssetRecord":
        from .linking_pdf import sha256_revision

        if (
            self.endpoint.locators
            or not all(
                getattr(self.endpoint, field)
                for field in ("edition_id", "package_id", "revision", "document_id")
            )
            or (self.format != "cusx" and self.endpoint.revision != sha256_revision(self.data))
            or (self.format == "cusx" and self.checksum != sha256_revision(self.data))
        ):
            raise ValueError("inventory asset requires complete identity and matching SHA-256")
        return self


class EntitlementRecord(Value):
    space_id: UUID
    user_id: UUID
    provider_id: NonEmpty
    provider_revision: NonEmpty
    resources: tuple[Endpoint, ...]


class BibleDetectionContext(Value):
    books: tuple[BibleBook, ...]
    profile: NonEmpty
    scheme_id: NonEmpty
    scheme_version: NonEmpty
    detector_revision: NonEmpty


class LinkingInventory(Value):
    entitlements: tuple[EntitlementRecord, ...] = ()
    bible: BibleDetectionContext | None = None
    catalog: tuple[CatalogEntry, ...] = ()
    passages: tuple[PassageEntry, ...] = ()
    snapshots: tuple[TextSnapshot, ...] = ()
    assets: tuple[AssetRecord, ...] = ()


class LinkingRuntime:
    def __init__(
        self,
        *,
        dsn: str,
        jwks_url: str,
        audience: str,
        inventory: LinkingInventory,
        scholarly_recognizer: ScholarlyCitationRecognizer | None = None,
        scholarly_revision: str | None = None,
    ):
        self.dsn = dsn
        self.jwks_url = jwks_url
        self.audience = audience
        self.inventory = LinkingInventory.model_validate(inventory.model_dump())
        if (scholarly_recognizer is None) != (
            scholarly_revision is None
        ) or scholarly_revision == "":
            raise ValueError("scholarly recognizer requires an explicit implementation revision")
        self.scholarly_recognizer = scholarly_recognizer
        self.scholarly_revision = scholarly_revision

    def store(self, space_id: UUID, token: str) -> PostgreSQLReferenceStore:
        return PostgreSQLReferenceStore(
            self.dsn, space_id=space_id, token=token, jwks_url=self.jwks_url, audience=self.audience
        )

    def synchronize_entitlements(
        self, store: PostgreSQLReferenceStore, user_id: UUID, *, expected_version: int | None
    ) -> int:
        from .linking_entitlements import EntitlementSnapshot, PostgreSQLEntitlementSynchronizer

        records = [
            record
            for record in self.inventory.entitlements
            if record.space_id == store.space_id and record.user_id == user_id
        ]
        if len(records) != 1:
            raise ValueError("trusted entitlement record unavailable or ambiguous")
        record = records[0]
        snapshot = EntitlementSnapshot(
            provider_id=record.provider_id,
            provider_revision=record.provider_revision,
            resources=record.resources,
        )
        return PostgreSQLEntitlementSynchronizer(store, provider_id=record.provider_id).synchronize(
            user_id, snapshot, expected_version=expected_version
        )

    def snapshot(self, store: PostgreSQLReferenceStore, source: Endpoint) -> TextSnapshot:
        with psycopg.connect(store.dsn) as db:
            actor = store._authorize(db, None)
            store._check_access(db, actor, source)
            matches = [
                snapshot for snapshot in self.inventory.snapshots if snapshot.endpoint == source
            ]
            if len(matches) != 1:
                raise ValueError("source snapshot unavailable or ambiguous")
            return matches[0]

    def conversion(
        self,
        store: PostgreSQLReferenceStore,
        original: Endpoint,
        converted: Endpoint,
        *,
        asset_id: str,
        stream_id: str,
    ):
        with psycopg.connect(store.dsn) as db:
            actor = store._authorize(db, "contribute")
            store._check_access(db, actor, (original, converted))
            matches = [
                asset
                for asset in self.inventory.assets
                if endpoint_scope(asset.endpoint)[0] == endpoint_scope(original)[0]
            ]
            if len(matches) != 1 or original.locators or converted.locators:
                raise ValueError("conversion requires an available whole asset")
            asset = matches[0]
            if asset.format == "pdf":
                from .linking_pymupdf import extract_pymupdf_references_input

                return extract_pymupdf_references_input(
                    asset.data,
                    original=original,
                    converted=converted,
                    asset_id=asset_id,
                    stream_id=stream_id,
                )
            if asset.format == "epub":
                from .linking_epub import extract_epub_references_input

                return extract_epub_references_input(
                    asset.data,
                    original=original,
                    converted=converted,
                    asset_id=asset_id,
                    stream_id=stream_id,
                )
            if asset.format != "html":
                raise ValueError("asset format has no conversion extractor")
            from .linking_html import extract_html_references_input

            return extract_html_references_input(
                asset.data,
                original=original,
                converted=converted,
                asset_id=asset_id,
                stream_id=stream_id,
            )

    def register_conversion(
        self,
        store: PostgreSQLReferenceStore,
        original: Endpoint,
        converted: Endpoint,
        *,
        asset_id: str,
        stream_id: str,
        event_id: UUID,
        reason: str,
    ):
        from .linking_postgres_events import PostgreSQLConversionEventRegistry

        context = self.inventory.bible
        if context is None:
            raise ValueError("citation detector context is not configured")
        conversion = self.conversion(
            store, original, converted, asset_id=asset_id, stream_id=stream_id
        )
        detector = BibleCitationDetector(
            books=context.books,
            stream_id=stream_id,
            profile=context.profile,
            scheme_id=context.scheme_id,
            scheme_version=context.scheme_version,
            agent_id="corpora:bible-detector",
        )
        return PostgreSQLConversionEventRegistry(store).register(
            conversion,
            detector,
            event_id=event_id,
            detector_revision=context.detector_revision,
            reason=reason,
        )

    def register_scholarly_conversion(
        self,
        store: PostgreSQLReferenceStore,
        original: Endpoint,
        converted: Endpoint,
        *,
        asset_id: str,
        stream_id: str,
        event_ids: tuple[UUID, ...],
        reason: str,
    ):
        """Persist every recognized mention, including unknowns, with explicit job IDs.

        The ingest job durably assigns one event ID per ordered mention before
        registration. Each mention commits atomically; partial jobs resume using
        those same IDs. This operation never deletes earlier discoveries.
        """
        from corpora_linking import Provenance, identify_scholarly_citation

        from .linking_postgres_discoveries import PostgreSQLDiscoveryStore

        if self.scholarly_recognizer is None:
            raise ValueError("scholarly recognizer is not configured")
        conversion = self.conversion(
            store, original, converted, asset_id=asset_id, stream_id=stream_id
        )
        mentions = tuple(self.scholarly_recognizer.recognize(conversion.converted))
        if len(mentions) != len(event_ids) or len(set(event_ids)) != len(event_ids):
            raise ValueError("each ordered scholarly mention requires its own durable event ID")
        discoveries = PostgreSQLDiscoveryStore(store)
        return tuple(
            discoveries.register(
                identify_scholarly_citation(
                    conversion.converted,
                    mention,
                    SnapshotCatalog(entries=self.inventory.catalog),
                    provenance=Provenance(
                        origin="automatic",
                        agent_id="corpora:scholarly-recognizer",
                        method=f"configured-recognizer:{self.scholarly_revision}",
                    ),
                ),
                conversion.converted,
                mappings=conversion.mappings,
                event_id=event_id,
                reason=reason,
            )
            for mention, event_id in zip(mentions, event_ids, strict=True)
        )

    def resolver(self, store: PostgreSQLReferenceStore) -> "AuthorizedInventoryResolver":
        return AuthorizedInventoryResolver(store, self.inventory)


class AuthorizedInventoryResolver:
    """Check grants before asset/snapshot retrieval; preserve stale/unavailable outcomes."""

    def __init__(self, store: PostgreSQLReferenceStore, inventory: LinkingInventory):
        self.store = store
        self.inventory = inventory
        self.base = SnapshotResolver(
            catalog=SnapshotCatalog(entries=inventory.catalog),
            passages=inventory.passages,
            snapshots=inventory.snapshots,
        )

    def resolve(self, request: Endpoint) -> ResolutionResult:
        with psycopg.connect(self.store.dsn) as db:
            actor = self.store._authorize(db, None)
            self.store._check_access(db, actor, request)
            # Passage mappings may point into another pinned edition. Authorize
            # each matching candidate before the base resolver examines its text.
            for passage in self.inventory.passages:
                if (
                    passage.citation in request.locators
                    and passage.target.work_id == request.work_id
                ):
                    self.store._check_access(db, actor, passage.target)
            native = request.locators and all(
                isinstance(
                    locator,
                    (PdfLocator, EpubLocator, HtmlTextLocator, HtmlRangeLocator, StructuralLocator),
                )
                for locator in request.locators
            )
            if not native:
                result = self.base.resolve(request)
                self.store._check_access(db, actor, result)
                return result
            scope = endpoint_scope(request)[0]
            assets = [
                asset
                for asset in self.inventory.assets
                if endpoint_scope(asset.endpoint)[0] == scope
            ]
            if len(assets) != 1:
                return ResolutionResult(
                    status="unavailable", diagnostics=("native asset unavailable or ambiguous",)
                )
            try:
                self._native(assets[0], request)
            except (ValueError, IndexError) as exc:
                return ResolutionResult(
                    status="unresolved",
                    diagnostics=("stale or unsupported native selection", type(exc).__name__),
                )
            return ResolutionResult(status="resolved", candidates=(request,))

    @staticmethod
    def _native(asset: AssetRecord, request: Endpoint) -> str:
        if asset.format == "cusx":
            from .linking_cusx import retrieve_cusx_selection

            return retrieve_cusx_selection(asset.data, request)
        if asset.format == "pdf":
            from .linking_pymupdf import retrieve_pdf_selection

            return retrieve_pdf_selection(asset.data, request)
        if asset.format == "epub":
            from .linking_cfi import retrieve_epub_cfi_selection

            return retrieve_epub_cfi_selection(asset.data, request)
        if len(request.locators) == 1 and isinstance(request.locators[0], HtmlRangeLocator):
            from .linking_html import retrieve_html_range

            return retrieve_html_range(asset.data, request)
        from .linking_html import retrieve_html_selection

        return retrieve_html_selection(asset.data, request)

    def retrieve(self, request: Endpoint) -> str:
        result = self.resolve(request)
        if result.status != "resolved" or result.candidates != (request,):
            raise ValueError("selection is stale, ambiguous or unavailable")
        with psycopg.connect(self.store.dsn) as db:
            actor = self.store._authorize(db, None)
            self.store._check_access(db, actor, request)
            from corpora_linking import TextLocator

            if len(request.locators) == 1 and isinstance(request.locators[0], TextLocator):
                locator = request.locators[0]
                snapshots = [
                    snapshot
                    for snapshot in self.inventory.snapshots
                    if endpoint_scope(snapshot.endpoint)[0] == endpoint_scope(request)[0]
                    and snapshot.stream_id == locator.stream_id
                ]
                if len(snapshots) != 1:
                    raise ValueError("selection snapshot ambiguous")
                return snapshots[0].text[locator.start : locator.end]
            assets = [
                asset
                for asset in self.inventory.assets
                if endpoint_scope(asset.endpoint)[0] == endpoint_scope(request)[0]
            ]
            if len(assets) != 1:
                raise ValueError("selection asset unavailable")
            return self._native(assets[0], request)


def configure_linking(
    app,
    *,
    dsn: str,
    jwks_url: str,
    audience: str,
    inventory: LinkingInventory,
    scholarly_recognizer: ScholarlyCitationRecognizer | None = None,
    scholarly_revision: str | None = None,
) -> None:
    """Trusted server startup hook; does not provision grants or open a database."""
    app.state.linking_runtime = LinkingRuntime(
        dsn=dsn,
        jwks_url=jwks_url,
        audience=audience,
        inventory=inventory,
        scholarly_recognizer=scholarly_recognizer,
        scholarly_revision=scholarly_revision,
    )
