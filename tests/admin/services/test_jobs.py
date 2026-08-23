"""JobManager and ConversionJob: ownership, queue cap, stall watchdog, errors."""

import time
from pathlib import Path

import pytest
from admin.parsers.schema import SourceFormat
from admin.services.jobs import (
    _MAX_LOG_LINES,
    ConversionJob,
    JobManager,
    JobQueueFullError,
    JobStatus,
    _slugify,
    result_filename_for,
)


class InlineExecutor:
    """Runs submitted work synchronously so tests are deterministic."""

    def submit(self, fn, *args):
        fn(*args)

    def shutdown(self, **kwargs):
        self.shutdown_kwargs = kwargs


class DeferredExecutor:
    """Holds submitted work so tests can control when (or if) it runs."""

    def __init__(self):
        self.pending = []

    def submit(self, fn, *args):
        self.pending.append((fn, args))

    def run_all(self):
        for fn, args in self.pending:
            fn(*args)
        self.pending.clear()

    def shutdown(self, **kwargs):
        pass


def make_manager(executor=None, **kwargs) -> JobManager:
    manager = JobManager(max_workers=1, **kwargs)
    manager._executor.shutdown(wait=False, cancel_futures=True)
    manager._executor = executor or InlineExecutor()
    return manager


def _job(**kwargs) -> ConversionJob:
    defaults = {"id": "j1", "source_format": SourceFormat.PLAIN, "name": "doc"}
    return ConversionJob(**{**defaults, **kwargs})


class TestIsVisibleTo:
    def test_ownerless_job_visible_to_everyone(self):
        assert _job(owner=None).is_visible_to({"sub": "anyone"}) is True

    def test_no_claims_sees_any_job(self):
        assert _job(owner="alice").is_visible_to(None) is True

    def test_owner_matches_sub(self):
        assert _job(owner="alice").is_visible_to({"sub": "alice"}) is True

    def test_mismatch_denied(self):
        assert _job(owner="alice").is_visible_to({"sub": "bob"}) is False

    def test_claims_without_sub_denied_for_owned_job(self):
        assert _job(owner="alice").is_visible_to({}) is False


class TestSlugify:
    def test_lowercases_and_dashes_whitespace(self):
        assert _slugify("My Doc") == "my-doc"

    def test_collapses_non_alnum_runs(self):
        assert _slugify("Summa Theologiae 1200 ENG") == "summa-theologiae-1200-eng"

    def test_strips_leading_and_trailing_dashes(self):
        assert _slugify("  ---Hello---  ") == "hello"

    def test_empty_for_punctuation_only(self):
        assert _slugify("!!!") == ""
        assert _slugify("") == ""
        assert _slugify("   ") == ""

    def test_none_treated_as_empty(self):
        assert _slugify(None) == ""  # type: ignore[arg-type]

    def test_preserves_alphanumeric_including_digits(self):
        assert _slugify("Book 1, v2") == "book-1-v2"


class TestResultFilename:
    def test_convert_job_ends_in_corpus(self):
        assert (
            result_filename_for("My Doc", SourceFormat.PLAIN)
            == "my-doc.corpus"
        )

    def test_ingest_job_ends_in_graph_json(self):
        # `/ingest` jobs record the detected suffix as a bare string, not a
        # SourceFormat -- the result is a graph.json, not a .corpus archive.
        assert (
            result_filename_for("My Doc", "docx") == "my-doc.graph.json"
        )

    def test_empty_name_falls_back_to_job_id(self):
        assert (
            result_filename_for("", SourceFormat.PLAIN, job_id="abc-123")
            == "abc-123.corpus"
        )

    def test_punctuation_only_name_falls_back_to_job_id(self):
        assert (
            result_filename_for("!!!", SourceFormat.PLAIN, job_id="abc-123")
            == "abc-123.corpus"
        )

    def test_empty_name_and_empty_job_id_falls_back_to_empty_stem(self):
        # The defensive final fallback: no name, no job_id -> just the suffix.
        # Real callers always pass a job_id, so this only documents the
        # degenerate case rather than exercising it in production.
        assert result_filename_for("", SourceFormat.PLAIN) == ".corpus"


class TestToDict:
    def test_owner_never_exposed(self):
        payload = _job(owner="alice").to_dict()
        assert "owner" not in payload

    def test_result_filename_always_present(self):
        # The exposed filename is derived from `name` (slugified) and the
        # source_format type -- always ending in `.corpus` for /convert jobs
        # (issue #108). It's available before the job finishes, so a client
        # can show the library name in its UI from the moment it submits.
        assert _job(name="My Doc").to_dict()["result_filename"] == "my-doc.corpus"

    def test_result_filename_uses_display_name_when_set(self):
        # Once the worker thread sets `display_name` (the human-readable
        # title from the source, see issue #109), the preview
        # `result_filename` is slugified from it -- so the on-disk archive
        # name follows the human title, not the upload filename stem.
        job = _job(name="summa-theologia-1200-ENG", display_name="Summa Theologiae")
        assert job.to_dict()["result_filename"] == "summa-theologiae.corpus"

    def test_result_filename_graph_json_for_ingest_job(self):
        # `/ingest` jobs record a bare detected-suffix string, not a
        # SourceFormat -- their result is a graph.json, not a .corpus.
        job = ConversionJob(
            id="j1", source_format="docx", name="My Doc"
        )
        assert job.to_dict()["result_filename"] == "my-doc.graph.json"

    def test_result_filename_tracks_result_path_name_when_set(self):
        # When `result_path` is set (the job finished), `result_filename`
        # echoes `result_path.name` -- a collision-aware `_run_conversion`
        # may have appended a uniqueness suffix to the on-disk file that the
        # client must echo back on download (issue #108).
        job = _job(
            name="My Doc",
            status=JobStatus.SUCCEEDED,
            result_path=Path("/r/my-doc-abcd1234.corpus"),
        )
        assert job.to_dict()["result_filename"] == "my-doc-abcd1234.corpus"

    def test_display_name_exposed(self):
        # `display_name` is the human-readable title from the source (issue
        # #109); `None` until the worker sets it, then present on the
        # running/succeeded status.
        assert _job().to_dict()["display_name"] is None
        assert _job(display_name="Summa Theologiae").to_dict()["display_name"] == "Summa Theologiae"

    def test_download_ready_requires_success_and_path(self):
        job = _job(status=JobStatus.SUCCEEDED, result_path=Path("/r/x.corpus"))
        assert job.to_dict()["download_ready"] is True
        assert _job(status=JobStatus.SUCCEEDED).to_dict()["download_ready"] is False
        assert (
            _job(status=JobStatus.RUNNING, result_path=Path("/r/x.corpus"))
            .to_dict()["download_ready"]
            is False
        )

    def test_last_log(self):
        job = _job(logs=["a", "b"])
        assert job.to_dict()["last_log"] == "b"
        assert _job().to_dict()["last_log"] is None


class TestSubmit:
    def test_successful_job_lifecycle(self, tmp_path):
        manager = make_manager()
        result = tmp_path / "out.corpus"
        job = manager.submit(
            source_format=SourceFormat.PLAIN, name="doc", fn=lambda: result
        )
        fetched = manager.get(job.id)
        assert fetched.status == JobStatus.SUCCEEDED
        assert fetched.result_path == result
        assert fetched.finished_at is not None

    def test_failure_stores_sanitized_error(self):
        manager = make_manager()

        def boom():
            raise RuntimeError("/private/tmp/secret/work_dir exploded")

        job = manager.submit(source_format=SourceFormat.PLAIN, name="doc", fn=boom)
        fetched = manager.get(job.id)
        assert fetched.status == JobStatus.FAILED
        assert fetched.error == f"Conversion failed: RuntimeError (job id {job.id})"
        assert "/private/tmp" not in fetched.error  # no internal paths leak

    def test_caller_supplied_job_id_used(self):
        manager = make_manager()
        job = manager.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"), job_id="fixed"
        )
        assert job.id == "fixed"

    def test_queue_cap_raises_without_running_fn(self):
        manager = make_manager(DeferredExecutor(), max_pending=2)
        sentinel = {"ran": False}

        def marker():
            sentinel["ran"] = True
            return Path("x")

        manager.submit(source_format=SourceFormat.PLAIN, name="1", fn=lambda: Path("x"))
        manager.submit(source_format=SourceFormat.PLAIN, name="2", fn=lambda: Path("x"))
        with pytest.raises(JobQueueFullError):
            manager.submit(source_format=SourceFormat.PLAIN, name="3", fn=marker)
        assert sentinel["ran"] is False

    def test_terminal_jobs_do_not_count_toward_cap(self):
        manager = make_manager(max_pending=1)  # inline: jobs finish immediately
        manager.submit(source_format=SourceFormat.PLAIN, name="1", fn=lambda: Path("x"))
        # Previous job is terminal, so this must be accepted.
        manager.submit(source_format=SourceFormat.PLAIN, name="2", fn=lambda: Path("x"))


class TestStallWatchdog:
    def test_running_job_marked_failed_past_timeout(self):
        manager = make_manager(DeferredExecutor(), stall_timeout_seconds=10)
        job = manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"))
        job.status = JobStatus.RUNNING
        job.started_at = time.time() - 60
        fetched = manager.get(job.id)
        assert fetched.status == JobStatus.FAILED
        assert "timed out" in fetched.error

    def test_fresh_running_job_untouched(self):
        manager = make_manager(DeferredExecutor(), stall_timeout_seconds=1000)
        job = manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"))
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        assert manager.get(job.id).status == JobStatus.RUNNING

    def test_late_result_does_not_clobber_stall_verdict(self):
        # The watchdog fires while fn() is still executing (simulated by
        # triggering the stall check from inside fn); when fn later succeeds,
        # _run must keep the watchdog's FAILED verdict.
        manager = make_manager(stall_timeout_seconds=10)

        def slow_then_succeed():
            job = manager._jobs["fixed"]
            job.started_at = time.time() - 60  # pretend we've run for a minute
            manager.get("fixed")  # watchdog marks the job FAILED
            assert job.status == JobStatus.FAILED
            return Path("late.corpus")

        manager.submit(
            source_format=SourceFormat.PLAIN,
            name="d",
            fn=slow_then_succeed,
            job_id="fixed",
        )
        job = manager._jobs["fixed"]
        assert job.status == JobStatus.FAILED
        assert job.result_path is None
        assert "timed out" in job.error


class TestLog:
    def test_appends_and_trims(self):
        manager = make_manager(DeferredExecutor())
        job = manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"))
        for i in range(_MAX_LOG_LINES + 10):
            manager.log(job.id, f"line {i}")
        assert len(job.logs) == _MAX_LOG_LINES
        assert job.logs[-1] == f"line {_MAX_LOG_LINES + 9}"
        assert job.logs[0] == "line 10"  # oldest lines dropped

    def test_unknown_job_id_is_noop(self):
        make_manager().log("nope", "message")  # must not raise


class TestSetDisplayName:
    def test_sets_display_name_on_job(self):
        manager = make_manager(DeferredExecutor())
        job = manager.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x")
        )
        assert job.display_name is None
        manager.set_display_name(job.id, "Summa Theologiae")
        assert job.display_name == "Summa Theologiae"

    def test_unknown_job_id_is_noop(self):
        make_manager().set_display_name("nope", "title")  # must not raise


class TestShutdown:
    def test_shutdown_does_not_wait(self):
        executor = InlineExecutor()
        manager = make_manager(executor)
        manager.shutdown()
        assert executor.shutdown_kwargs == {"wait": False, "cancel_futures": True}
