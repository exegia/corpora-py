"""Structured conversion telemetry: boundaries, transport, persistence and isolation."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from admin.parsers.schema import SourceFormat
from admin.services import api as api_module
from admin.services import conversion, websocket
from admin.services.job_store_supabase import job_from_row, job_to_row
from admin.services.jobs import (
    _MAX_EVENT_MESSAGE_CHARS,
    _MAX_JOB_EVENTS,
    ConversionJob,
    JobManager,
    JobStatus,
    MemoryJobStore,
)

STAGES = ["metadata", "convert", "package", "validate"]


def _summary(valid=True):
    return {
        "valid": valid,
        "stats": {"review_items": 0},
        "checks": ["archive"],
        "reasons": [] if valid else ["Broken structure"],
    }


def _post(client, output_format="corpus"):
    response = client.post(
        "/convert",
        files={"file": ("document.txt", b"Sample text.", "text/plain")},
        data={"source_format": "plain", "name": "Document", "output_format": output_format},
    )
    assert response.status_code == 202
    return response.json()["job_id"]


def _patch_pipeline(monkeypatch, output_format="corpus", converter=None):
    def package(_tf, output, **kwargs):
        output.write_bytes(b"archive")
        return output

    monkeypatch.setitem(
        api_module.CONVERTERS,
        SourceFormat.PLAIN,
        converter or (lambda *args, **kwargs: SimpleNamespace(category=None, warnings=[])),
    )
    monkeypatch.setattr(api_module, "convert_to_corpus", package)
    monkeypatch.setattr(conversion, "validate_archive", lambda archive: _summary())
    if output_format in {"ctei", "cusx"}:
        from admin.converters import cusx, tei

        def combined(_source, output, **kwargs):
            return package(None, output)

        module = tei if output_format == "ctei" else cusx
        monkeypatch.setattr(module, f"convert_to_{output_format}", combined)


def _assert_events(events):
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(set(sequences))
    for event in events:
        assert set(event) == {"sequence", "timestamp", "level", "message", "stage"}
        assert isinstance(event["sequence"], int)
        assert isinstance(event["timestamp"], float)
        assert event["timestamp"] > 0
        assert event["level"] in {"debug", "info", "warning", "error"}
        assert isinstance(event["message"], str)
        assert event["stage"] is None or event["stage"] in STAGES


@pytest.mark.parametrize("output_format", ["corpus", "ctei", "cusx"])
def test_queued_and_success_telemetry_in_poll_list_and_ws(
    client, manager, monkeypatch, output_format
):
    _patch_pipeline(monkeypatch, output_format)
    job_id = _post(client, output_format)
    queued = client.get(f"/convert/{job_id}").json()
    assert queued["logs"] == [] and queued["last_log"] is None
    assert queued["events"][0]["message"] == "Conversion queued."
    assert [step["id"] for step in queued["steps"]] == STAGES
    assert all(step["status"] == "pending" for step in queued["steps"])
    manager._executor.run_all()
    payload = client.get(f"/convert/{job_id}").json()
    assert payload["status"] == "succeeded"
    assert [step["status"] for step in payload["steps"]] == [
        "completed",
        "completed",
        "completed" if output_format == "corpus" else "skipped",
        "completed",
    ]
    _assert_events(payload["events"])
    messages = [event["message"] for event in payload["events"]]
    assert messages[0:2] == ["Conversion queued.", "Conversion started."]
    assert messages[-1] == "Conversion succeeded."
    assert "Archive validation passed." in messages
    assert not any(event["level"] == "error" for event in payload["events"])
    assert client.get("/convert").json()["jobs"][0] == payload
    with client.websocket_connect(f"/convert/{job_id}/ws") as ws:
        assert ws.receive_json() == payload
    if output_format == "corpus":
        assert payload["logs"] == [
            "Parsing plain source and building Text-Fabric dataset...",
            "Text-Fabric dataset ready. Compiling cache and packaging .corpus archive...",
            "Validating converted corpus...",
            "Conversion complete.",
        ]
    assert payload["last_log"] == payload["logs"][-1]
    assert "progress" not in payload and "percentage" not in payload


def test_callbacks_bracket_actual_calls_and_keep_external_source(monkeypatch, tmp_path):
    source = tmp_path / "original.txt"
    source.write_text("Original")
    work = tmp_path / "intermediates"
    work.mkdir()
    transitions = []
    logs = []

    def check(stage):
        assert transitions[-1] == (stage, "running")

    def metadata(**kwargs):
        check("metadata")
        return "Document"

    def converter(*args, **kwargs):
        check("convert")
        return SimpleNamespace(category=None, warnings=[])

    def package(_tf, output, **kwargs):
        check("package")
        return output

    def validate(archive):
        check("validate")
        return _summary()

    monkeypatch.setattr(conversion, "derive_display_name", metadata)
    monkeypatch.setattr(conversion, "validate_archive", validate)
    result = conversion.run_conversion(
        source_path=source,
        work_dir=work,
        source_format=SourceFormat.PLAIN,
        output_path_for=lambda display: tmp_path / "result.corpus",
        converters={SourceFormat.PLAIN: converter},
        convert_fn=package,
        on_stage=lambda stage, status: transitions.append((stage, status)),
        on_log=logs.append,
    )
    assert result == tmp_path / "result.corpus"
    assert transitions == [
        (stage, status) for stage in STAGES for status in ("running", "completed")
    ]
    assert source.read_text() == "Original"
    assert not work.exists()
    assert logs[-1] == "Conversion complete."


@pytest.mark.parametrize("stage", STAGES)
def test_failure_is_attributed_to_actual_stage_and_upload_is_cleaned(
    client, manager, monkeypatch, stage
):
    _patch_pipeline(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("secret-token in /private/server/path")

    if stage == "metadata":
        monkeypatch.setattr(conversion, "derive_display_name", boom)
    elif stage == "convert":
        monkeypatch.setitem(api_module.CONVERTERS, SourceFormat.PLAIN, boom)
    elif stage == "package":
        monkeypatch.setattr(api_module, "convert_to_corpus", boom)
    else:
        monkeypatch.setattr(conversion, "validate_archive", boom)
    job_id = _post(client)
    source = next(api_module._WORK_ROOT.glob("*/source/*"))
    manager._executor.run_all()
    payload = client.get(f"/convert/{job_id}").json()
    assert payload["status"] == "failed" and not payload["download_ready"]
    assert "RuntimeError" in payload["error"]
    index = STAGES.index(stage)
    assert [step["status"] for step in payload["steps"]] == (
        ["completed"] * index + ["failed"] + ["skipped"] * (3 - index)
    )
    assert payload["events"][-1]["stage"] == stage
    assert payload["events"][-1]["level"] == "error"
    assert payload["events"][-1]["message"] == "Conversion failed."
    assert "secret-token" not in json.dumps(payload)
    assert "/private/server/path" not in json.dumps(payload)
    assert not source.exists() and not source.parent.parent.exists()


@pytest.mark.parametrize("output_format", ["corpus", "ctei", "cusx"])
def test_invalid_validation_summary_survives_failed_job(
    client, manager, monkeypatch, output_format
):
    _patch_pipeline(monkeypatch, output_format)
    summary = _summary(False)
    monkeypatch.setattr(conversion, "validate_archive", lambda archive: summary)
    job_id = _post(client, output_format)
    manager._executor.run_all()
    payload = client.get(f"/convert/{job_id}").json()
    assert payload["validation"] == summary
    assert payload["status"] == "failed" and payload["steps"][-1]["status"] == "failed"
    assert payload["events"][-1]["stage"] == "validate"
    assert not payload["download_ready"]
    assert not any("CTEI archive validated" in line for line in payload["logs"])
    assert any(
        event["level"] == "error" and event["message"] == "Archive validation failed."
        for event in payload["events"]
    )


@pytest.mark.parametrize("output_format", ["corpus", "ctei", "cusx"])
def test_validator_private_error_is_sanitized_and_attributed_to_validate(
    client, manager, monkeypatch, output_format
):
    _patch_pipeline(monkeypatch, output_format)

    def broken_validator(archive):
        raise ValueError(f"Cannot read {archive}: private validator detail")

    monkeypatch.setattr(conversion, "validate_archive", broken_validator)
    job_id = _post(client, output_format)
    manager._executor.run_all()
    payload = client.get(f"/convert/{job_id}").json()
    assert payload["status"] == "failed"
    assert payload["steps"][-1]["status"] == "failed"
    assert payload["events"][-1]["stage"] == "validate"
    assert payload["validation"] is None
    assert "private validator detail" not in json.dumps(payload)
    assert str(api_module._RESULTS_ROOT) not in json.dumps(payload)


def test_result_store_failure_does_not_falsely_fail_validate(client, manager, monkeypatch):
    _patch_pipeline(monkeypatch)

    def broken_save(*args):
        raise RuntimeError("private storage detail")

    monkeypatch.setattr(manager._results, "save", broken_save)
    job_id = _post(client)
    manager._executor.run_all()
    payload = client.get(f"/convert/{job_id}").json()
    assert payload["status"] == "failed" and not payload["download_ready"]
    assert all(step["status"] == "completed" for step in payload["steps"])
    assert payload["validation"]["valid"] is True
    assert payload["events"][-1]["stage"] is None
    assert "private storage detail" not in json.dumps(payload)


@pytest.mark.parametrize("output_format", ["ctei", "cusx"])
@pytest.mark.parametrize("stage", ["convert", "validate"])
def test_combined_output_failure_attribution(client, manager, monkeypatch, output_format, stage):
    _patch_pipeline(monkeypatch, output_format)

    def boom(*args, **kwargs):
        raise ValueError("Invalid input structure")

    if stage == "validate":
        monkeypatch.setattr(conversion, "validate_archive", boom)
    else:
        from admin.converters import cusx, tei

        monkeypatch.setattr(
            tei if output_format == "ctei" else cusx, f"convert_to_{output_format}", boom
        )
    job_id = _post(client, output_format)
    manager._executor.run_all()
    payload = client.get(f"/convert/{job_id}").json()
    assert payload["status"] == "failed"
    assert payload["events"][-1]["stage"] == stage
    assert next(step for step in payload["steps"] if step["id"] == stage)["status"] == "failed"


def test_debug_options_and_warning_events_do_not_copy_private_metadata(
    client, manager, monkeypatch
):
    def converter(source, _tf, **kwargs):
        return SimpleNamespace(category=None, warnings=[f"Warning referencing {source}"])

    _patch_pipeline(monkeypatch, converter=converter)
    monkeypatch.setattr(conversion, "derive_display_name", lambda **kwargs: "SECRET TITLE")
    response = client.post(
        "/convert",
        files={"file": ("source.txt", b"text")},
        data={"source_format": "plain", "name": "SECRET NAME", "description": "SECRET TOKEN"},
    )
    manager._executor.run_all()
    payload = client.get(f"/convert/{response.json()['job_id']}").json()
    telemetry = json.dumps(payload["events"])
    assert "SECRET" not in telemetry
    assert str(api_module._WORK_ROOT) not in telemetry
    assert str(api_module._RESULTS_ROOT) not in telemetry
    assert any(event["level"] == "debug" for event in payload["events"])
    assert any(event["level"] == "warning" for event in payload["events"])
    assert any("private path omitted" in event["message"] for event in payload["events"])
    # Legacy logs are deliberately unchanged, even when an existing caller supplied a path.
    assert any(str(api_module._WORK_ROOT) in line for line in payload["logs"])


def test_events_are_bounded_and_sequence_continues_under_concurrent_writes(manager):
    job = manager.submit(
        job_id="bounded", source_format=SourceFormat.PLAIN, name="D", fn=lambda: None
    )

    def write(worker):
        for index in range(100):
            manager.event(job.id, "debug", f"worker={worker}; item={index}", "convert")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(4)))
    payload = job.to_dict()
    assert len(payload["events"]) == _MAX_JOB_EVENTS
    assert [event["sequence"] for event in payload["events"]] == list(range(202, 402))
    manager.event(job.id, "debug", "x" * (_MAX_EVENT_MESSAGE_CHARS + 1))
    assert job.events[-1]["sequence"] == 402
    assert len(job.events[-1]["message"]) == _MAX_EVENT_MESSAGE_CHARS
    # A payload is detached from subsequent updates and cannot mutate the job.
    payload["events"][-1]["message"] = "changed"
    payload["steps"][0]["status"] = "failed"
    assert job.events[-2]["message"] != "changed"
    assert job.steps[0]["status"] == "pending"
    manager.event("unknown", "info", "ignored")
    manager.set_stage("unknown", "convert", "running")


def test_stall_marks_active_stage_failed_and_late_telemetry_cannot_undo_it(manager):
    job = manager.submit(source_format=SourceFormat.PLAIN, name="D", fn=lambda: None)
    job.status = JobStatus.RUNNING
    job.started_at = time.time() - 10000
    manager.set_stage(job.id, "metadata", "completed")
    manager.set_stage(job.id, "convert", "running")
    manager.get(job.id)
    assert job.status == JobStatus.FAILED
    assert [step["status"] for step in job.steps] == ["completed", "failed", "skipped", "skipped"]
    snapshot = job.to_dict()
    manager.set_stage(job.id, "convert", "completed")
    manager.event(job.id, "debug", "late", "convert")
    assert job.to_dict() == snapshot
    assert job.events[-1]["message"] == "Conversion timed out."
    assert job.events[-1]["stage"] == "convert"


def test_parallel_pipeline_jobs_have_isolated_telemetry(monkeypatch, tmp_path):
    manager = JobManager(max_workers=2)
    monkeypatch.setattr(api_module, "job_manager", manager)
    monkeypatch.setattr(api_module, "_RESULTS_ROOT", tmp_path / "results")
    rendezvous = Barrier(2)
    release = Event()

    def converter(source, _tf, **kwargs):
        marker = Path(source).read_text()
        rendezvous.wait(timeout=5)
        assert release.wait(5)
        return SimpleNamespace(category=None, warnings=[f"Warning for {marker}"])

    _patch_pipeline(monkeypatch, converter=converter)
    jobs = []
    try:
        for marker in ("ALPHA", "BETA"):
            work = tmp_path / marker
            work.mkdir()
            source = work / "source.txt"
            source.write_text(marker)
            jobs.append(
                manager.submit(
                    job_id=marker,
                    source_format=SourceFormat.PLAIN,
                    name=marker,
                    fn=lambda source=source, work=work, marker=marker: api_module._run_conversion(
                        source_path=source,
                        work_dir=work,
                        source_format=SourceFormat.PLAIN,
                        name=marker,
                        description="",
                        job_id=marker,
                    ),
                )
            )
        release.set()
        for job in jobs:
            job.completion.result(timeout=10)
        for job, other in ((jobs[0], "BETA"), (jobs[1], "ALPHA")):
            payload = manager.get(job.id).to_dict()
            assert payload["status"] == "succeeded", payload
            assert f"Warning for {job.id}" in payload["logs"]
            assert other not in json.dumps(payload["events"])
            assert any(event["message"] == f"Warning for {job.id}" for event in payload["events"])
            assert payload["events"][0]["sequence"] == 1
            _assert_events(payload["events"])
            assert not (tmp_path / job.id).exists()
    finally:
        release.set()
        rendezvous.abort()
        manager.shutdown(wait=True)


@pytest.mark.parametrize("as_json_string", [False, True])
def test_supabase_envelope_round_trip_without_new_columns(manager, as_json_string):
    job = manager.submit(source_format=SourceFormat.PLAIN, name="D", fn=lambda: None)
    manager.set_stage(job.id, "convert", "running")
    manager.log(job.id, "legacy checkpoint")
    row = job_to_row(job)
    assert "events" not in row and "steps" not in row
    assert set(row["logs"]) == {"logs", "events", "steps"}
    if as_json_string:
        row["logs"] = json.dumps(row["logs"])
    restored = job_from_row(row)
    assert restored.to_dict() == job.to_dict()
    assert restored.logs == ["legacy checkpoint"]


@pytest.mark.parametrize("logs", [[], ["old checkpoint"], '["old checkpoint"]'])
def test_legacy_supabase_rows_have_empty_telemetry(logs):
    row = job_to_row(ConversionJob(id="old", source_format=SourceFormat.PLAIN, name="D"))
    row["logs"] = logs
    restored = job_from_row(row)
    assert restored.events == [] and restored.steps == []
    assert restored.to_dict()["logs"] == ([] if logs == [] else ["old checkpoint"])


def test_shared_row_store_preserves_queued_diagnostics_and_terminal_telemetry(manager):
    class RowStore(MemoryJobStore):
        def put(self, job):
            self._jobs[job.id] = job_to_row(job)

        def get(self, job_id):
            row = self._jobs.get(job_id)
            return job_from_row(row) if row else None

        def list(self, *, owner):
            return [job_from_row(row) for row in self._jobs.values()]

    manager._store = RowStore()

    def work():
        manager.set_stage("shared", "metadata", "running")
        manager.set_stage("shared", "metadata", "completed")
        manager.set_validation("shared", _summary())
        return None

    job = manager.submit(job_id="shared", source_format=SourceFormat.PLAIN, name="D", fn=work)
    manager.log(job.id, "Queued upload warning", level="warning")
    manager._executor.run_all()
    restored = manager.get(job.id)
    assert restored.status == JobStatus.SUCCEEDED
    assert restored.logs == ["Queued upload warning"]
    assert restored.steps[0]["status"] == "completed"
    assert restored.validation == _summary()
    _assert_events(restored.events)
    assert [event["sequence"] for event in restored.events] == list(
        range(1, len(restored.events) + 1)
    )
    assert any(event["message"] == "Queued upload warning" for event in restored.events)
    assert restored.events[-1]["message"] == "Conversion succeeded."


def test_telemetry_openapi_has_typed_items_and_backward_compatible_defaults(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    status = schemas["ConversionJobStatus"]
    for field in ("events", "steps"):
        assert field not in status["required"]
        assert status["properties"][field]["default"] == []
        assert "$ref" in status["properties"][field]["items"]
    event = schemas["ConversionJobEvent"]
    assert set(event["required"]) == {"sequence", "timestamp", "level", "message", "stage"}
    assert event["properties"]["level"]["enum"] == ["debug", "info", "warning", "error"]
    assert schemas["ConversionJobStep"]["properties"]["status"]["enum"] == [
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
    ]
    payload = ConversionJob(id="old", source_format=SourceFormat.PLAIN, name="D").to_dict()
    payload.pop("events")
    payload.pop("steps")
    model = api_module.ConversionJobStatus.model_validate(payload)
    assert model.events == [] and model.steps == []


@pytest.mark.parametrize("transport", ["poll", "list", "ws"])
def test_transport_serializes_under_manager_lock(client, manager, monkeypatch, transport):
    job = manager.submit(source_format=SourceFormat.PLAIN, name="D", fn=lambda: None)
    job.status = JobStatus.FAILED
    original = ConversionJob.to_dict

    def checked_snapshot(self):
        # Otherwise a worker can publish terminal status between serialization
        # of status and events, and a WebSocket closes with no terminal event.
        assert manager._lock.locked()
        return original(self)

    monkeypatch.setattr(ConversionJob, "to_dict", checked_snapshot)
    if transport == "ws":
        with client.websocket_connect(f"/convert/{job.id}/ws") as ws:
            assert ws.receive_json()["status"] == "failed"
    else:
        response = client.get(f"/convert/{job.id}" if transport == "poll" else "/convert")
        assert response.status_code == 200


def test_validation_payload_is_detached(manager):
    job = manager.submit(source_format=SourceFormat.PLAIN, name="D", fn=lambda: None)
    summary = _summary()
    manager.set_validation(job.id, summary)
    payload = job.to_dict()
    payload["validation"]["checks"].append("client change")
    assert job.validation == _summary()


def test_ws_resends_telemetry_only_changes_at_buffer_capacity(client, manager, monkeypatch):
    monkeypatch.setattr(websocket, "_POLL_INTERVAL_SECONDS", 0.001)
    job = manager.submit(source_format=SourceFormat.PLAIN, name="D", fn=lambda: None)
    job.status = JobStatus.RUNNING
    job.started_at = time.time()
    for index in range(_MAX_JOB_EVENTS):
        manager.event(job.id, "debug", f"checkpoint {index}")
    with client.websocket_connect(f"/convert/{job.id}/ws") as ws:
        first = ws.receive_json()
        assert len(first["events"]) == _MAX_JOB_EVENTS
        manager.event(job.id, "debug", "new event", "convert")
        second = ws.receive_json()
        assert len(second["events"]) == _MAX_JOB_EVENTS
        assert second["events"][-1]["sequence"] == first["events"][-1]["sequence"] + 1
        assert second["logs"] == first["logs"] == []
        manager.set_stage(job.id, "convert", "running")
        third = ws.receive_json()
        assert third["steps"][1]["status"] == "running"
        job.status = JobStatus.FAILED
        assert ws.receive_json()["status"] == "failed"
