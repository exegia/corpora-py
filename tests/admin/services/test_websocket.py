"""/convert/{id}/ws: 4404 gating, status/log push, terminal close."""

from pathlib import Path

from admin.parsers.schema import SourceFormat
from admin.services.jobs import JobStatus
from starlette.websockets import WebSocketDisconnect


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


def test_progress_push_continues_after_log_history_reaches_cap(client, manager):
    from admin.services.jobs import _MAX_LOG_LINES
    job = _submit(manager)
    job.status = JobStatus.RUNNING
    for index in range(_MAX_LOG_LINES):
        manager.log(job.id, f"page {index}")
    with client.websocket_connect(f"/convert/{job.id}/ws") as ws:
        first = ws.receive_json()
        manager.log(job.id, "new page after history cap")
        second = ws.receive_json()
        assert len(first["logs"]) == len(second["logs"]) == _MAX_LOG_LINES
        assert second["last_log"] == "new page after history cap"


def test_rest_status_preserves_confirmed_pdf_page_counts(client, manager):
    from admin.parsers.pdf_progress import report_page, report_pdf_progress
    job = _submit(manager, source_format=SourceFormat.PDF)
    job.status = JobStatus.RUNNING
    with report_pdf_progress(lambda line: manager.log(job.id, line)):
        report_page(54, 232)
    response = client.get(f"/convert/{job.id}")
    assert response.status_code == 200
    assert response.json()["progress"]["completed_pages"] == 54
    assert response.json()["progress"]["total_pages"] == 232
