"""Loopback-only browser demo over real SQLite lifecycle and snapshot retrieval.

Synthetic actor tokens are demo fixtures, not production authentication.
"""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID

import uvicorn
from corpora_linking import (
    CatalogEntry,
    Endpoint,
    Provenance,
    Reference,
    SnapshotCatalog,
    SnapshotResolver,
    TextLocator,
    TextSnapshot,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from corpora_py.linking_api import Decision, SaveLink
from corpora_py.linking_store import SQLiteReferenceStore, VersionConflictError

app = FastAPI(title="Local reference linking demo")
workspace = TemporaryDirectory(prefix="linking-browser-demo-")
path = Path(workspace.name) / "references.sqlite"
space_id = "00000000-0000-4000-8000-000000000001"
prefix = f"/linking/{space_id}"


def snapshot(work: str, text: str) -> TextSnapshot:
    return TextSnapshot(
        endpoint=Endpoint(
            work_id=work,
            edition_id="demo-edition",
            package_id=work,
            revision="demo-version-1",
            document_id="chapter",
        ),
        stream_id="body",
        text=text,
    )


source = snapshot("demo-essay", "😀 Before. The linked passage. After.")
target = snapshot("demo-target", "Before. A verse-like destination. After.")
resolver = SnapshotResolver(
    catalog=SnapshotCatalog(
        entries=(
            CatalogEntry(work_id=source.endpoint.work_id, names=("Essay",)),
            CatalogEntry(work_id=target.endpoint.work_id, names=("Destination",)),
        )
    ),
    snapshots=(source, target),
)


@contextmanager
def operation(request: Request, *, review: bool = False):
    token = request.headers.get("authorization", "")
    actors = {"Bearer demo-reader": "demo-reader", "Bearer demo-reviewer": "demo-reviewer"}
    if token not in actors:
        raise HTTPException(401, "Choose a demo reader or reviewer")
    if review and actors[token] != "demo-reviewer":
        raise HTTPException(403, "Choose Reviewer to approve")
    try:
        yield SQLiteReferenceStore(path, actor_id=actors[token])
    except VersionConflictError as exc:
        raise HTTPException(409, "Reference changed; reload before retrying") from exc
    except ValueError as exc:
        raise HTTPException(422, "Selection is stale or the transition is invalid") from exc


@app.get("/demo/config")
def config():
    return {"spaceId": space_id, "source": source, "target": target}


@app.post(prefix + "/references")
def save(body: SaveLink, request: Request):
    with operation(request) as store:
        previous = store.get(body.reference.id) if body.expected_version is not None else None
        provenance = (
            previous.provenance
            if previous
            else Provenance(origin="manual", agent_id=store.actor_id, method="reader-selection")
        )
        reference = Reference.model_validate(
            {
                **body.reference.model_dump(),
                "provenance": provenance,
                "review": "pending",
                "publication": "draft",
                "resolution": "unresolved",
            }
        )
        version = store.save(reference, expected_version=body.expected_version, reason=body.reason)
        return {"version": version, "reference": store.get(reference.id)}


@app.get(prefix + "/references/{reference_id}")
def history(reference_id: UUID, request: Request):
    with operation(request) as store:
        result = store.history(reference_id)
        if not result:
            raise HTTPException(404, "Reference not found")
        return {"history": result}


@app.post(prefix + "/references/{reference_id}/{action}")
def decide(
    reference_id: UUID, action: Literal["resolve", "approve"], body: Decision, request: Request
):
    with operation(request, review=action == "approve") as store:
        method = store.approve if action == "approve" else store.resolve_target
        version = method(
            reference_id,
            expected_version=body.expected_version,
            reason=body.reason,
            resolver=resolver,
        )
        return {"version": version}


@app.post(prefix + "/retrieve")
def retrieve(endpoint: Endpoint, request: Request):
    with operation(request):
        result = resolver.resolve(endpoint)
        if result.status != "resolved" or result.candidates != (endpoint,):
            raise ValueError("stale, ambiguous or unavailable selection")
        if len(endpoint.locators) != 1 or not isinstance(endpoint.locators[0], TextLocator):
            raise ValueError("exact text selection required")
        locator = endpoint.locators[0]
        matches = [
            item
            for item in resolver.snapshots
            if item.endpoint == endpoint.model_copy(update={"locators": ()})
            and item.stream_id == locator.stream_id
        ]
        if len(matches) != 1:
            raise ValueError("snapshot unavailable or ambiguous")
        return {"text": matches[0].text[locator.start : locator.end]}


app.mount("/", StaticFiles(directory=Path(__file__).parent, html=True), name="client")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8787)
