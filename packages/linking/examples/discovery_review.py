"""Local unknown citation -> catalog refresh -> reviewed work choice -> pending link."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from corpora_linking import (
    CatalogEntry,
    Endpoint,
    Provenance,
    ScholarlyCitationMention,
    SnapshotCatalog,
    TextLocator,
    TextSnapshot,
    identify_scholarly_citation,
)

from corpora_py.linking_discoveries import SQLiteDiscoveryStore
from corpora_py.linking_store import SQLiteReferenceStore


def discovery_review() -> dict:
    text = "Example Author, Notes"
    snapshot = TextSnapshot(
        endpoint=Endpoint(
            work_id="fixture:essay",
            edition_id="fixture",
            package_id="source",
            revision="1",
            document_id="body",
        ),
        stream_id="body",
        text=text,
    )
    mention = ScholarlyCitationMention(
        selection=TextLocator(stream_id="body", start=0, end=len(text), exact=text), cited_name=text
    )
    discovery = identify_scholarly_citation(
        snapshot,
        mention,
        SnapshotCatalog(),
        provenance=Provenance(
            origin="automatic", agent_id="fixture-recognizer", method="explicit-span"
        ),
    )
    with TemporaryDirectory() as directory:
        path = Path(directory) / "working.db"
        creator = SQLiteDiscoveryStore(
            SQLiteReferenceStore(path, actor_id="creator"), authority_id="fixture"
        )
        event_id = uuid4()
        registered = creator.register(
            discovery, snapshot, event_id=event_id, reason="catalog unknown"
        )
        reviewer_store = SQLiteReferenceStore(path, actor_id="reviewer")
        reviewer = SQLiteDiscoveryStore(reviewer_store, authority_id="fixture")
        catalog = SnapshotCatalog(
            entries=(
                CatalogEntry(work_id="fixture:notes", names=(text,)),
                CatalogEntry(work_id="fixture:other", names=(text,)),
            )
        )
        identified = reviewer.refresh_identification(
            discovery.id, snapshot, catalog, expected_version=1, reason="bibliographic evidence"
        )
        selected = reviewer.select_work(
            discovery.id, "fixture:notes", expected_version=2, reason="reviewed work identity"
        )
        retry = creator.register(discovery, snapshot, event_id=event_id, reason="retry")
        assert retry == registered
        assert selected.selected_reference_id is not None
        reference = reviewer_store.get(selected.selected_reference_id)
        assert (
            reference is not None
            and reference.review == "pending"
            and reference.resolution == "unresolved"
        )
        return {
            "history": [item.model_dump(mode="json") for item in reviewer.history(discovery.id)],
            "identified": identified.discovery.work_identification.status,
            "reference": reference.model_dump(mode="json"),
            "retry_preserved_ids": retry.discovery.id == discovery.id,
        }


if __name__ == "__main__":
    print(json.dumps(discovery_review(), ensure_ascii=False, indent=2))
