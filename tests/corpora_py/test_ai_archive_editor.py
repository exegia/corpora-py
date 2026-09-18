"""Real TF/CFM archive edits, provenance and source-text preservation."""

import json
import zipfile
from uuid import uuid4

import pytest
import yaml
from test_ai_service import archive as archive

from corpora_py.ai.archive_editor import digest, edit_archive, inspect_archive
from corpora_py.ai.schemas import NodeScope, Suggestion
from corpora_py.ai.scope import scope_content_hash, scope_nodes
from corpora_py.ai.service import CurationError
from corpora_py.ai.wal_supabase import DraftHead


@pytest.fixture
def selection(archive, tmp_path):
    from cfabric import Fabric

    api = Fabric(locations=str(archive.parent / "tf"), silent="deep").loadAll(silent="deep")
    scope = NodeScope(
        corpus="mini",
        version="v1.0",
        level="section",
        node_id=13,
        node_type="chapter",
        label="Chapter",
    )
    content_hash = scope_content_hash(api, scope_nodes(api, scope))
    scope.content_hash = content_hash
    owner, document, revision = (str(uuid4()) for _ in range(3))
    head = DraftHead(
        owner=owner,
        document_id=document,
        corpus="mini",
        bucket="corpus-ai-drafts",
        object_key=f"{owner}/ai/{document}/{revision}.corpus",
        revision=revision,
        digest=digest(archive),
        version="v1.0",
    )
    proposal = Suggestion(
        id="suggestion",
        scope=scope,
        kind="label",
        target_node=13,
        diff=[{"field": "chapter", "old": "1", "new": "3"}],
        rationale="Correct chapter label",
        base_version="v1.0",
        content_hash=content_hash,
    )
    return head, proposal


def test_edit_rebuilds_cache_and_preserves_history(archive, selection, tmp_path):
    head, proposal = selection
    original = archive.read_bytes()
    output = tmp_path / "edited.corpus"
    plan = edit_archive(archive, output, head, proposal)
    assert archive.read_bytes() == original
    assert plan.after.values["chapter"] == "3"
    assert plan.before.values["chapter"] == "1"
    assert plan.after.content_hash == plan.before.content_hash
    assert plan.after.version == "v1.1"
    current = head.model_copy(
        update={
            "revision": plan.after.revision,
            "digest": plan.after.digest,
            "version": plan.after.version,
            "object_key": head.key_for(plan.after.revision),
        }
    )
    assert inspect_archive(output, current, proposal) == plan.after
    with zipfile.ZipFile(output) as packed:
        history = yaml.safe_load(packed.read("history.yml"))["versions"]
        assert history[-1]["snapshot_key"] == current.object_key
        assert history[-1]["ai_change"]["resp"] == ["#corpora-ai", "#" + head.owner]
        assert history[0]["current"] is False
        assert json.loads(packed.read("ai-changes.json"))[-1]["diff"][0]["old"] == "1"
        assert yaml.safe_load(packed.read("toc.yml"))["version"] == "v1.1"
        assert "corpora/chapter.tf" in packed.namelist()
        assert any("/.cfm/" in name for name in packed.namelist())


@pytest.mark.parametrize(
    "field,new",
    [
        ("text", "forged"),
        ("otype", "word"),
        ("../chapter", "3"),
        ("missing", "3"),
        ("chapter", "3.0"),
    ],
)
def test_unsafe_or_ill_typed_feature_is_rejected(archive, selection, tmp_path, field, new):
    head, proposal = selection
    proposal.diff[0].field = field
    proposal.diff[0].new = new
    original = archive.read_bytes()
    with pytest.raises(CurationError):
        edit_archive(archive, tmp_path / "out.corpus", head, proposal)
    assert archive.read_bytes() == original
    assert not (tmp_path / "out.corpus").exists()


@pytest.mark.parametrize("change", ["version", "hash", "old", "target", "kind"])
def test_stale_and_out_of_scope_edits_fail(archive, selection, tmp_path, change):
    head, proposal = selection
    if change == "version":
        proposal.base_version = "v0.9"
    elif change == "hash":
        proposal.content_hash = "wrong"
    elif change == "old":
        proposal.diff[0].old = "9"
    elif change == "target":
        proposal.target_node = 14
    else:
        from corpora_py.ai.schemas import SuggestionKind

        proposal.kind = SuggestionKind.boundary
    with pytest.raises(CurationError):
        edit_archive(archive, tmp_path / "out.corpus", head, proposal)


def test_inverse_edit_keeps_both_provenance_entries(archive, selection, tmp_path):
    head, proposal = selection
    output = tmp_path / "one.corpus"
    first = edit_archive(archive, output, head, proposal)
    head = head.model_copy(
        update={
            "revision": first.after.revision,
            "digest": first.after.digest,
            "version": first.after.version,
            "object_key": head.key_for(first.after.revision),
        }
    )
    proposal.scope.version = first.after.version
    proposal.base_version = first.after.version
    proposal.diff[0].old = "3"
    proposal.diff[0].new = "1"
    proposal.id = "undo:original-operation"
    second = edit_archive(output, tmp_path / "two.corpus", head, proposal)
    assert second.after.values == first.before.values
    assert second.after.version == "v1.2"
    with zipfile.ZipFile(tmp_path / "two.corpus") as packed:
        assert len(json.loads(packed.read("ai-changes.json"))) == 2


def test_real_archive_adapter_apply_undo_and_restart(archive, selection, tmp_path):
    import shutil
    from datetime import UTC, datetime

    from corpora_py.ai.archive_editor import ArchiveDrafts
    from corpora_py.ai.wal import MutationEngine, Receipt
    from corpora_py.ai.wal_sqlite import SQLiteJournal

    head, proposal = selection

    class LocalPublisher:
        def __init__(self):
            self.head = head
            self.objects = {head.object_key: archive}
            self.receipts = {}

        def resolve(self, owner, corpus):
            assert owner == head.owner and corpus == head.corpus
            return self.head.model_copy()

        def download(self, current, destination):
            shutil.copyfile(self.objects[current.object_key], destination)

        def stage(self, current, revision, path, expected):
            assert digest(path) == expected
            key = current.key_for(revision)
            target = tmp_path / (revision + ".corpus")
            shutil.copyfile(path, target)
            self.objects[key] = target

        def publish(self, intent):
            if self.head.revision != intent.plan.before.revision:
                return False
            after = intent.plan.after
            self.head = self.head.model_copy(
                update={
                    "revision": after.revision,
                    "digest": after.digest,
                    "version": after.version,
                    "object_key": self.head.key_for(after.revision),
                }
            )
            self.receipts[intent.id] = Receipt(proof=intent.proof, applied_at=datetime.now(UTC))
            return True

        def receipt(self, owner, operation):
            return self.receipts.get(operation)

    publisher = LocalPublisher()
    journal = SQLiteJournal(tmp_path / "journal.db")
    engine = MutationEngine(journal, ArchiveDrafts(publisher))
    applied = engine.apply(head.owner, proposal)
    with zipfile.ZipFile(publisher.objects[publisher.head.object_key]) as packed:
        assert json.loads(packed.read("ai-changes.json"))[-1]["operation_id"] == applied.intent.id
    engine = MutationEngine(SQLiteJournal(tmp_path / "journal.db"), ArchiveDrafts(publisher))
    assert engine.apply(head.owner, proposal) == applied
    reverted = engine.undo(head.owner, applied.intent.id)
    assert reverted.intent.plan.after.values == applied.intent.plan.before.values
    assert publisher.head.version == "v1.2"
    with zipfile.ZipFile(publisher.objects[publisher.head.object_key]) as packed:
        assert (
            json.loads(packed.read("ai-changes.json"))[-1]["reverts_operation_id"]
            == applied.intent.id
        )
    assert (
        inspect_archive(
            publisher.objects[publisher.head.object_key], publisher.head, proposal
        ).values
        == applied.intent.plan.before.values
    )


def test_unrelated_assets_and_string_escaping_survive(archive, selection, tmp_path):
    head, proposal = selection
    # Add a typed metadata feature and an unrelated binary asset to the fixture.
    edited = tmp_path / "with-note.corpus"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(edited, "w") as target:
        for name in source.namelist():
            if "/.cfm/" not in name:
                target.writestr(name, source.read(name))
        target.writestr("corpora/note.tf", "@node\n@valueType=str\n\n13\told\n")
        target.writestr("assets/keep.bin", b"\x00\x01retain")
    head = head.model_copy(update={"digest": digest(edited)})
    from corpora_py.ai.schemas import DiffRow

    proposal.diff.append(DiffRow(field="note", old="old", new="new\tvalue\nline\\tail"))
    result = edit_archive(edited, tmp_path / "out.corpus", head, proposal)
    assert result.after.values["note"] == "new\tvalue\nline\\tail"
    with zipfile.ZipFile(tmp_path / "out.corpus") as packed:
        assert packed.read("assets/keep.bin") == b"\x00\x01retain"
        provenance = json.loads(packed.read("ai-changes.json"))
        assert len(provenance[-1]["diff"]) == 2


def test_stale_cache_drift_outside_selection_cannot_be_published(archive, selection, tmp_path):
    head, proposal = selection
    broken = tmp_path / "inconsistent.corpus"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(broken, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "corpora/text.tf":
                data = data.replace(b"8\teight", b"8\tchanged-outside-scope")
            target.writestr(name, data)
    head = head.model_copy(update={"digest": digest(broken)})
    with pytest.raises(CurationError) as error:
        edit_archive(broken, tmp_path / "out.corpus", head, proposal)
    assert error.value.status == 422
    assert not (tmp_path / "out.corpus").exists()
