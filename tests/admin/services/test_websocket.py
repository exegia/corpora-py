"""/convert/{id}/ws: 4404 gating, status/log push, terminal close."""

from pathlib import Path

from starlette.websockets import WebSocketDisconnect

from admin.parsers.schema import SourceFormat
from admin.services.jobs import JobStatus


def _submit(manager, **kwargs):
    defaults = {"source_format": SourceFormat.PLAIN, "name": "doc", "fn": lambda: Path("x")}
    return manager.submit(**{**defaults, **kwargs})


class TestGating:
    def test_unknown_job_closes_4404(self, client):
        try:
            with client.websocket_connect("/convert/nope/ws") as ws:
                ws.receive_json()
        except WebSocketDisconnect as exc:
            assert exc.code == 4404
        else:  # pragma: no cover
            raise AssertionError("expected 4404 close")

    def test_other_users_job_closes_4404(self, client, manager, claims_holder):
        job = _submit(manager, owner="alice")
        claims_holder["claims"] = {"sub": "mallory"}
        try:
            with client.websocket_connect(f"/convert/{job.id}/ws") as ws:
                ws.receive_json()
        except WebSocketDisconnect as exc:
            assert exc.code == 4404
        else:  # pragma: no cover
            raise AssertionError("expected 4404 close")


class TestPush:
    def test_terminal_job_pushes_snapshot_then_closes(self, client, manager):
        job = _submit(manager)
        job.status = JobStatus.SUCCEEDED
        job.result_path = Path("done.corpus")
        with client.websocket_connect(f"/convert/{job.id}/ws") as ws:
            snapshot = ws.receive_json()
            assert snapshot["status"] == "succeeded"
            assert snapshot["download_ready"] is True

    def test_own_job_accessible_with_matching_claims(self, client, manager, claims_holder):
        claims_holder["claims"] = {"sub": "alice"}
        job = _submit(manager, owner="alice")
        job.status = JobStatus.FAILED
        job.error = "Conversion failed: RuntimeError (job id x)"
        with client.websocket_connect(f"/convert/{job.id}/ws") as ws:
            snapshot = ws.receive_json()
            assert snapshot["status"] == "failed"
            assert "owner" not in snapshot
