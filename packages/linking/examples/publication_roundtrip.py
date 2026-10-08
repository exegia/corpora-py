"""Offline approved snapshot export/import; no external publication."""

import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

from corpora_py.linking_publication import SnapshotPublicationAdapter
from corpora_py.linking_store import SQLiteReferenceStore


def publication_roundtrip():
    example = runpy.run_path(str(Path(__file__).with_name("review_link.py")))
    reviewed = example["review_link"]()[-1]
    adapter = SnapshotPublicationAdapter("fixture:reviewed-working-store")
    payload = adapter.export(
        (reviewed.reference,), versions={reviewed.reference.id: reviewed.version}
    )
    with TemporaryDirectory() as folder:
        target = SQLiteReferenceStore(Path(folder) / "imported.db", actor_id="importer")
        (decision,) = adapter.plan_import(payload, target)
        adapter.apply_import(decision, target, reason="import approved snapshot for local review")
        (repeated,) = adapter.plan_import(payload, target)
        assert repeated.outcome == "unchanged"
        assert target.get(reviewed.reference.id).review == "pending"
        assert target.get(reviewed.reference.id).publication == "draft"
        return payload, target.history(reviewed.reference.id)


if __name__ == "__main__":
    payload, history = publication_roundtrip()
    print(payload.decode())
    print(history[-1].reference.model_dump_json())
