import json
import runpy
from pathlib import Path
from uuid import UUID

import pytest

from corpora_py.linking_events import ConversionEvent
from corpora_py.linking_publication import PublicationSnapshot
from corpora_py.linking_store import SQLiteReferenceStore


def example():
    return runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "packages/linking/examples/end_to_end.py")
    )


def test_real_html_to_manual_and_automatic_review_export_and_withdrawal(tmp_path):
    summary = example()["run_example"](tmp_path)
    assert summary["retry_preserved_ids"] is True
    assert summary["automatic_id"] != summary["manual_id"]
    assert summary["retrieved_target"] == "Fixture verse text."
    assert (summary["exported_count"], summary["next_export_count"]) == (2, 1)
    auto_id, manual_id = UUID(summary["automatic_id"]), UUID(summary["manual_id"])
    working = SQLiteReferenceStore(tmp_path / "working.db", actor_id="test-reader")
    assert [x.action for x in working.history(auto_id)] == [
        "edit",
        "resolve",
        "approve",
        "publish",
        "withdraw",
    ]
    assert [x.action for x in working.history(manual_id)] == [
        "edit",
        "resolve",
        "approve",
        "publish",
    ]
    assert working.get(auto_id).publication == "withdrawn"
    assert working.get(manual_id).publication == "published"
    assert working.history(auto_id)[0].reference.target.locators[0].kind == "citation"
    assert (
        working.history(auto_id)[2].reference.target
        == working.history(manual_id)[2].reference.target
    )
    event = ConversionEvent.model_validate_json((tmp_path / "conversion-event.json").read_bytes())
    assert event.report.references[0].reference.id == auto_id
    assert len(event.report.references[0].mappings) == 2
    snapshot = PublicationSnapshot.model_validate_json(
        (tmp_path / "approved-snapshot.json").read_bytes()
    )
    assert {x.reference.id for x in snapshot.entries} == {auto_id, manual_id}
    assert all(x.working_version == 3 for x in snapshot.entries)
    after = PublicationSnapshot.model_validate_json(
        (tmp_path / "after-withdrawal.json").read_bytes()
    )
    assert [x.reference.id for x in after.entries] == [manual_id]
    imported = SQLiteReferenceStore(tmp_path / "imported.db", actor_id="test-reader")
    assert all(
        len(imported.history(x)) == 1 and imported.get(x).review == "pending"
        for x in (auto_id, manual_id)
    )
    assert len(json.loads((tmp_path / "publication-history.json").read_text())) == 3


def test_example_refuses_nonempty_output_directory(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("existing data")
    with pytest.raises(ValueError, match="must be empty"):
        example()["run_example"](tmp_path)
    assert marker.read_text() == "existing data"
