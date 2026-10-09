"""Opt-in linking HTTP orchestration; configuration/authorities are server-owned."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from corpora_linking import Endpoint, Provenance, Reference, ScholarlyCitationMention
from corpora_linking.models import NonEmpty, Value
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field

if TYPE_CHECKING:
    from .linking_runtime import LinkingRuntime

router = APIRouter(prefix="/linking", tags=["linking"])


class SaveLink(Value):
    reference: Reference
    expected_version: int | None = Field(default=None, ge=1, strict=True)
    reason: NonEmpty


class Decision(Value):
    expected_version: int = Field(ge=1, strict=True)
    reason: NonEmpty
    allow_unresolved_target: bool = False


class ExportRequest(Value):
    reference_ids: tuple[UUID, ...]


class PublicationRequest(Decision):
    event_id: UUID
    snapshot: str | None = None


class DiscoveryRequest(Value):
    source: Endpoint
    mention: ScholarlyCitationMention
    event_id: UUID
    reason: NonEmpty


class WorkChoice(Decision):
    work_id: NonEmpty | None = None


def _configured(request: Request) -> "LinkingRuntime":
    runtime = getattr(request.app.state, "linking_runtime", None)
    if runtime is None:
        raise HTTPException(503, "Reference linking is unavailable")
    return runtime


@contextmanager
def _operation(request: Request, space_id: UUID):
    runtime = _configured(request)
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Sign in to manage references")
    import psycopg
    from common.utils.jwt_auth import AuthError

    from .linking_store import VersionConflictError

    try:
        yield runtime, runtime.store(space_id, token)
    except AuthError as exc:
        raise HTTPException(401, "Session is invalid or expired") from exc
    except PermissionError as exc:
        raise HTTPException(403, "Reference access denied") from exc
    except VersionConflictError as exc:
        raise HTTPException(409, "Reference changed; reload before retrying") from exc
    except (ValueError, IndexError) as exc:
        raise HTTPException(422, "Reference selection or transition is invalid") from exc
    except (psycopg.Error, ImportError) as exc:
        raise HTTPException(503, "Reference linking is unavailable") from exc


@router.post("/{space_id}/references")
def save_link(space_id: UUID, body: SaveLink, request: Request):
    with _operation(request, space_id) as (runtime, store):
        previous = store.get(body.reference.id) if body.expected_version is not None else None
        provenance = (
            previous.provenance
            if previous is not None
            else Provenance(origin="manual", agent_id=store.actor_id, method="reader-selection")
        )
        # Edits retain creator identity; creation derives it from the verified actor.
        reference = Reference.model_validate(
            {
                **body.reference.model_dump(),
                "provenance": provenance,
                "resolution": "unresolved",
                "review": "pending",
                "publication": "draft",
            }
        )
        version = store.save(reference, expected_version=body.expected_version, reason=body.reason)
        return {"version": version, "reference": store.get(reference.id)}


@router.get("/{space_id}/references/{reference_id}")
def reference_history(space_id: UUID, reference_id: UUID, request: Request):
    with _operation(request, space_id) as (runtime, store):
        history = store.history(reference_id)
        if not history:
            raise HTTPException(404, "Reference not found")
        return {"history": history}


@router.post("/{space_id}/references/{reference_id}/{action}")
def reference_decision(
    space_id: UUID,
    reference_id: UUID,
    action: Literal["resolve", "approve", "reject", "reopen"],
    body: Decision,
    request: Request,
):
    with _operation(request, space_id) as (runtime, store):
        parameters = dict(expected_version=body.expected_version, reason=body.reason)
        if action == "resolve":
            version = store.resolve_target(
                reference_id, resolver=runtime.resolver(store), **parameters
            )
        elif action == "approve":
            version = store.approve(
                reference_id,
                resolver=runtime.resolver(store),
                allow_unresolved_target=body.allow_unresolved_target,
                **parameters,
            )
        elif action == "reject":
            version = store.reject(reference_id, **parameters)
        else:
            version = store.reopen(reference_id, **parameters)
        return {"version": version}


@router.post("/{space_id}/retrieve")
def retrieve_selection(space_id: UUID, endpoint: Endpoint, request: Request):
    with _operation(request, space_id) as (runtime, store):
        return {"text": runtime.resolver(store).retrieve(endpoint)}


@router.post("/{space_id}/export")
def export_references(space_id: UUID, body: ExportRequest, request: Request):
    with _operation(request, space_id) as (runtime, store):
        from .linking_postgres_events import PostgreSQLPublicationLedger

        return Response(
            PostgreSQLPublicationLedger(store).export_current(body.reference_ids),
            media_type="application/json",
        )


@router.post("/{space_id}/publication/{reference_id}/{action}")
def publication(
    space_id: UUID,
    reference_id: UUID,
    action: Literal["acknowledge", "withdraw"],
    body: PublicationRequest,
    request: Request,
):
    with _operation(request, space_id) as (runtime, store):
        from .linking_postgres_events import PostgreSQLPublicationLedger

        ledger = PostgreSQLPublicationLedger(store)
        if action == "acknowledge":
            if body.snapshot is None:
                raise HTTPException(422, "Approved snapshot is required")
            return ledger.acknowledge_snapshot(
                body.snapshot.encode(),
                reference_id,
                event_id=body.event_id,
                expected_version=body.expected_version,
                reason=body.reason,
            )
        return ledger.withdraw(
            reference_id,
            event_id=body.event_id,
            expected_version=body.expected_version,
            reason=body.reason,
        )


@router.post("/{space_id}/discoveries")
def register_discovery(space_id: UUID, body: DiscoveryRequest, request: Request):
    with _operation(request, space_id) as (runtime, store):
        from corpora_linking import SnapshotCatalog, identify_scholarly_citation

        from .linking_postgres_discoveries import PostgreSQLDiscoveryStore

        snapshot = runtime.snapshot(store, body.source)
        discovery = identify_scholarly_citation(
            snapshot,
            body.mention,
            SnapshotCatalog(entries=runtime.inventory.catalog),
            provenance=Provenance(
                origin="automatic", agent_id=store.actor_id, method="submitted-scholarly-span"
            ),
        )
        return PostgreSQLDiscoveryStore(store).register(
            discovery, snapshot, event_id=body.event_id, reason=body.reason
        )


@router.get("/{space_id}/discoveries/{discovery_id}")
def discovery_history(space_id: UUID, discovery_id: UUID, request: Request):
    with _operation(request, space_id) as (runtime, store):
        from .linking_postgres_discoveries import PostgreSQLDiscoveryStore

        return {"history": PostgreSQLDiscoveryStore(store).history(discovery_id)}


@router.post("/{space_id}/discoveries/{discovery_id}/{action}")
def discovery_decision(
    space_id: UUID,
    discovery_id: UUID,
    action: Literal["identify", "reject", "select"],
    body: WorkChoice,
    request: Request,
):
    with _operation(request, space_id) as (runtime, store):
        from corpora_linking import SnapshotCatalog

        from .linking_postgres_discoveries import PostgreSQLDiscoveryStore

        discoveries = PostgreSQLDiscoveryStore(store)
        if action == "select":
            if body.work_id is None:
                raise HTTPException(422, "Choose an identified work")
            return discoveries.select_work(
                discovery_id,
                body.work_id,
                expected_version=body.expected_version,
                reason=body.reason,
            )
        if action == "reject":
            return discoveries.reject(
                discovery_id, expected_version=body.expected_version, reason=body.reason
            )
        discovery = discoveries.get(discovery_id)
        if discovery is None:
            raise HTTPException(404, "Citation discovery not found")
        snapshot = runtime.snapshot(store, discovery.source.model_copy(update={"locators": ()}))
        return discoveries.refresh_identification(
            discovery_id,
            snapshot,
            SnapshotCatalog(entries=runtime.inventory.catalog),
            expected_version=body.expected_version,
            reason=body.reason,
        )


class ConversionRequest(Value):
    original: Endpoint
    converted: Endpoint
    asset_id: NonEmpty
    stream_id: NonEmpty = "body"
    event_id: UUID
    reason: NonEmpty


@router.post("/{space_id}/conversion-events")
def conversion_event(space_id: UUID, body: ConversionRequest, request: Request):
    with _operation(request, space_id) as (runtime, store):
        return runtime.register_conversion(
            store,
            body.original,
            body.converted,
            asset_id=body.asset_id,
            stream_id=body.stream_id,
            event_id=body.event_id,
            reason=body.reason,
        )


class ImportRequest(Value):
    snapshot: str


@router.post("/{space_id}/import-plan")
def import_plan(space_id: UUID, body: ImportRequest, request: Request):
    with _operation(request, space_id) as (runtime, store):
        import psycopg

        from .linking_postgres_events import _authority
        from .linking_publication import SnapshotPublicationAdapter

        with psycopg.connect(store.dsn) as db:
            actor = store._authorize(db, "contribute")
            from .linking_publication import PublicationSnapshot

            snapshot = PublicationSnapshot.model_validate_json(body.snapshot)
            store._check_access(db, actor, snapshot)
            authority = _authority(db, store)
        return {
            "decisions": SnapshotPublicationAdapter(authority).plan_import(
                body.snapshot.encode(), store
            )
        }


class ApplyImportRequest(Value):
    snapshot: str
    reference_id: UUID
    expected_version: int | None = Field(default=None, ge=1, strict=True)
    reason: NonEmpty


@router.post("/{space_id}/import")
def apply_import(space_id: UUID, body: ApplyImportRequest, request: Request):
    """Recompute the decision server-side; no client-supplied approval/decision."""
    with _operation(request, space_id) as (runtime, store):
        import psycopg

        from .linking_postgres_events import _authority
        from .linking_publication import PublicationSnapshot, SnapshotPublicationAdapter
        from .linking_store import VersionConflictError

        snapshot = PublicationSnapshot.model_validate_json(body.snapshot)
        with psycopg.connect(store.dsn) as db:
            actor = store._authorize(db, "contribute")
            store._check_access(db, actor, snapshot)
            authority = _authority(db, store)
        adapter = SnapshotPublicationAdapter(authority)
        decisions = adapter.plan_import(body.snapshot.encode(), store)
        selected = [item for item in decisions if item.entry.reference.id == body.reference_id]
        if len(selected) != 1:
            raise HTTPException(422, "Reference is absent from snapshot")
        decision = selected[0]
        if decision.expected_version != body.expected_version:
            raise VersionConflictError("import version changed")
        return {"version": adapter.apply_import(decision, store, reason=body.reason)}


class CUSXRequest(ExportRequest):
    source: Endpoint
    # Typed in the endpoint body below without importing XML libraries on startup.
    bindings: tuple[dict, ...] = ()


@router.post("/{space_id}/export-cusx")
def export_cusx(space_id: UUID, body: CUSXRequest, request: Request):
    with _operation(request, space_id) as (runtime, store):
        import psycopg

        from .linking_access import endpoint_scope
        from .linking_cusx import AnchorBinding, publish_cusx_links, validate_cusx_binding
        from .linking_postgres_events import PostgreSQLPublicationLedger
        from .linking_publication import PublicationSnapshot

        publication = PublicationSnapshot.model_validate_json(
            PostgreSQLPublicationLedger(store).export_current(body.reference_ids)
        )
        bindings = tuple(AnchorBinding.model_validate(value) for value in body.bindings)
        with psycopg.connect(store.dsn) as db:
            actor = store._authorize(db, None)
            store._check_access(db, actor, (body.source, bindings, publication))

            def asset_for(endpoint):
                matches = [
                    asset
                    for asset in runtime.inventory.assets
                    if asset.format == "cusx"
                    and endpoint_scope(asset.endpoint)[0] == endpoint_scope(endpoint)[0]
                ]
                if len(matches) != 1:
                    raise ValueError("published C-USX document unavailable or ambiguous")
                return matches[0]

            source_asset = asset_for(body.source)
            source_snapshot = runtime.snapshot(store, body.source)
            for binding in bindings:
                target_asset = asset_for(binding.selection)
                target_snapshot = runtime.snapshot(store, target_asset.endpoint)
                validate_cusx_binding(target_asset.data, target_snapshot, binding)
            # Structural destinations also require actual advertised anchors.
            from corpora_linking import StructuralLocator
            from lxml import etree

            from .linking_cusx import CX

            for entry in publication.entries:
                for locator in entry.reference.target.locators:
                    if isinstance(locator, StructuralLocator):
                        target_asset = asset_for(entry.reference.target)
                        root = etree.fromstring(
                            target_asset.data,
                            etree.XMLParser(resolve_entities=False, no_network=True),
                        )
                        matches = [
                            element
                            for element in root.iter()
                            if element.get(f"{{{CX}}}id") == locator.anchor_id
                        ]
                        if len(matches) != 1:
                            raise ValueError("structural destination is not uniquely advertised")
            xml = publish_cusx_links(
                source_asset.data, source_snapshot, publication, target_bindings=bindings
            )
        return {"cusx": xml.decode("utf-8"), "snapshot": publication}


class ScholarlyConversionRequest(Value):
    original: Endpoint
    converted: Endpoint
    asset_id: NonEmpty
    stream_id: NonEmpty = "body"
    event_ids: tuple[UUID, ...]
    reason: NonEmpty


@router.post("/{space_id}/scholarly-conversion-events")
def scholarly_conversion_events(space_id: UUID, body: ScholarlyConversionRequest, request: Request):
    with _operation(request, space_id) as (runtime, store):
        return {
            "discoveries": runtime.register_scholarly_conversion(
                store,
                body.original,
                body.converted,
                asset_id=body.asset_id,
                stream_id=body.stream_id,
                event_ids=body.event_ids,
                reason=body.reason,
            )
        }


class BrowserSelectionRequest(Value):
    original: Endpoint
    asset_id: NonEmpty
    captured_nodes: tuple[tuple[tuple[int, ...], str], ...]
    start_path: tuple[int, ...]
    start_utf16: int = Field(ge=0, strict=True)
    end_path: tuple[int, ...]
    end_utf16: int = Field(ge=0, strict=True)


@router.post("/{space_id}/browser-selection")
def browser_selection(space_id: UUID, body: BrowserSelectionRequest, request: Request):
    with _operation(request, space_id) as (runtime, store):
        import psycopg

        from .linking_access import endpoint_scope
        from .linking_html_ranges import make_browser_html_range

        with psycopg.connect(store.dsn) as db:
            actor = store._authorize(db, None)
            store._check_access(db, actor, body.original)
            assets = [
                asset
                for asset in runtime.inventory.assets
                if asset.format == "html"
                and endpoint_scope(asset.endpoint)[0] == endpoint_scope(body.original)[0]
            ]
            if len(assets) != 1:
                raise ValueError("HTML asset unavailable or ambiguous")
            endpoint = make_browser_html_range(
                assets[0].data,
                body.original,
                asset_id=body.asset_id,
                captured_nodes=body.captured_nodes,
                start_path=body.start_path,
                start_utf16=body.start_utf16,
                end_path=body.end_path,
                end_utf16=body.end_utf16,
            )
        return {"endpoint": endpoint, "text": runtime.resolver(store).retrieve(endpoint)}
