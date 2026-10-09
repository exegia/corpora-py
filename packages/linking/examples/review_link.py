"""Local review workflow example; requires the Corpora umbrella package."""

from pathlib import Path
from tempfile import TemporaryDirectory

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

from corpora_py.linking_store import SQLiteReferenceStore


def review_link():
    base = Endpoint(
        work_id="essay", edition_id="e", package_id="p", revision="fixture:1", document_id="chapter"
    )
    text = "Selected sentence."
    source = Endpoint.model_validate(
        {
            **base.model_dump(),
            "locators": [TextLocator(stream_id="body", start=0, end=len(text), exact=text)],
        }
    )
    reference = Reference(
        source=source,
        target=Endpoint(work_id="book"),
        provenance=Provenance(origin="manual", agent_id="reader", method="selection"),
    )
    resolver = SnapshotResolver(
        catalog=SnapshotCatalog(
            entries=(
                CatalogEntry(work_id="essay", names=("Essay",)),
                CatalogEntry(work_id="book", names=("Book",)),
            )
        ),
        snapshots=(TextSnapshot(endpoint=base, stream_id="body", text=text),),
    )
    with TemporaryDirectory() as folder:
        path = Path(folder) / "working.db"
        creator = SQLiteReferenceStore(path, actor_id="reader")
        version = creator.save(reference, expected_version=None, reason="manual selection")
        reviewer = SQLiteReferenceStore(path, actor_id="reviewer")
        reviewer.approve(
            reference.id,
            expected_version=version,
            resolver=resolver,
            reason="verified source and whole work",
        )
        history = reviewer.history(reference.id)
        assert history[-1].reference.id == reference.id
        assert history[-1].reference.publication == "draft"
        return history


if __name__ == "__main__":
    for revision in review_link():
        print(revision.model_dump_json())
