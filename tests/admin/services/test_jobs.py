"""JobManager and ConversionJob: ownership, queue cap, stall watchdog, errors."""

import copy
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
    JobStore,
    JobStoreError,
    LocalResultStore,
    MemoryJobStore,
    ResultStore,
    _slugify,
    make_job_store,
    make_result_store,
    result_filename_for,
    snapshot_key_for,
)
from common.utils.config import settings


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

    def test_download_ready_with_result_key_without_local_path(self):
        # Another instance has the metadata but not the file; download_ready
        # must still be true so the client polls through to materialize.
        job = _job(status=JobStatus.SUCCEEDED, result_key="conversion-jobs/j1.corpus")
        assert job.to_dict()["download_ready"] is True
        assert "result_key" not in job.to_dict()

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
            job = manager._store.get("fixed")
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
        job = manager._store.get("fixed")
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


class TestListJobs:
    def test_returns_all_jobs_for_owner(self):
        manager = make_manager(DeferredExecutor())
        manager.submit(source_format=SourceFormat.PLAIN, name="a", fn=lambda: Path("x"), owner="alice", job_id="j1")
        manager.submit(source_format=SourceFormat.PLAIN, name="b", fn=lambda: Path("x"), owner="alice", job_id="j2")
        manager.submit(source_format=SourceFormat.PLAIN, name="c", fn=lambda: Path("x"), owner="bob", job_id="j3")
        jobs, total = manager.list_jobs(owner="alice")
        assert total == 2
        assert {j.id for j in jobs} == {"j1", "j2"}

    def test_no_owner_returns_all(self):
        manager = make_manager(DeferredExecutor())
        manager.submit(source_format=SourceFormat.PLAIN, name="a", fn=lambda: Path("x"), owner="alice", job_id="j1")
        manager.submit(source_format=SourceFormat.PLAIN, name="b", fn=lambda: Path("x"), owner="bob", job_id="j2")
        jobs, total = manager.list_jobs(owner=None)
        assert total == 2

    def test_sorted_most_recent_first(self):
        import time as _time

        manager = make_manager(DeferredExecutor())
        manager.submit(source_format=SourceFormat.PLAIN, name="old", fn=lambda: Path("x"), owner="u", job_id="j1")
        # Ensure created_at differs.
        _time.sleep(0.01)
        manager.submit(source_format=SourceFormat.PLAIN, name="new", fn=lambda: Path("x"), owner="u", job_id="j2")
        jobs, _ = manager.list_jobs(owner="u")
        assert jobs[0].id == "j2"
        assert jobs[1].id == "j1"

    def test_pagination(self):
        manager = make_manager(DeferredExecutor())
        for i in range(5):
            manager.submit(source_format=SourceFormat.PLAIN, name=f"j{i}", fn=lambda: Path("x"), owner="u", job_id=f"j{i}")
        jobs, total = manager.list_jobs(owner="u", offset=1, limit=2)
        assert total == 5
        assert len(jobs) == 2

    def test_empty_store(self):
        manager = make_manager()
        jobs, total = manager.list_jobs(owner="alice")
        assert total == 0
        assert jobs == []


class TestReapExpired:
    def test_reaps_terminal_jobs_past_retention(self, tmp_path):
        manager = make_manager(DeferredExecutor(), retention_seconds=60)
        # Submit a job and let it succeed.
        result = tmp_path / "result.corpus"
        result.write_bytes(b"data")
        manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: result, owner="u", job_id="j1")
        manager._executor.run_all()
        job = manager.get("j1")
        assert job.status == JobStatus.SUCCEEDED
        # Pretend it finished long ago.
        with manager._lock:
            job.finished_at = time.time() - 120
            manager._store.put(job)
        assert result.exists()
        # Trigger reap via list_jobs.
        manager.list_jobs(owner="u")
        assert manager.get("j1") is None
        assert not result.exists()

    def test_does_not_reap_non_terminal(self, tmp_path):
        manager = make_manager(DeferredExecutor(), retention_seconds=60)
        manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"), owner="u", job_id="j1")
        # Job is QUEUED (deferred executor, not run).
        manager.list_jobs(owner="u")
        assert manager.get("j1") is not None

    def test_does_not_reap_recent_terminal(self, tmp_path):
        manager = make_manager(DeferredExecutor(), retention_seconds=3600)
        manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"), owner="u", job_id="j1")
        manager._executor.run_all()
        manager.list_jobs(owner="u")
        assert manager.get("j1") is not None

    def test_disabled_by_default(self, tmp_path):
        manager = make_manager(DeferredExecutor())
        manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"), owner="u", job_id="j1")
        manager._executor.run_all()
        job = manager.get("j1")
        with manager._lock:
            job.finished_at = time.time() - 999999
            manager._store.put(job)
        manager.list_jobs(owner="u")
        assert manager.get("j1") is not None


class TestCustomStore:
    def test_custom_store_is_used(self):
        class RecordingStore(JobStore):
            def __init__(self):
                self._d = {}
                self.puts = 0

            def get(self, job_id):
                return self._d.get(job_id)

            def put(self, job):
                self._d[job.id] = job
                self.puts += 1

            def list(self, *, owner):
                return list(self._d.values())

            def delete(self, job_id):
                return self._d.pop(job_id, None)

        store = RecordingStore()
        manager = make_manager(DeferredExecutor(), store=store)
        manager.submit(source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"), owner="u", job_id="j1")
        assert store.puts >= 1
        assert manager.get("j1") is not None

    def test_memory_store_list_filters_by_owner(self):
        store = MemoryJobStore()
        j1 = ConversionJob(id="j1", source_format=SourceFormat.PLAIN, name="a", owner="alice")
        j2 = ConversionJob(id="j2", source_format=SourceFormat.PLAIN, name="b", owner="bob")
        store.put(j1)
        store.put(j2)
        assert len(store.list(owner="alice")) == 1
        assert len(store.list(owner="bob")) == 1
        assert len(store.list(owner=None)) == 2

    def test_memory_store_delete(self):
        store = MemoryJobStore()
        j = ConversionJob(id="j1", source_format=SourceFormat.PLAIN, name="a")
        store.put(j)
        assert store.delete("j1") is j
        assert store.delete("j1") is None


class CopyingJobStore(JobStore):
    """Stand-in for a remote store: every get/put round-trips a copy.

    Catches JobManager bugs that rely on in-process object identity (the
    MemoryJobStore default), which a shared PostgREST store cannot provide.
    """

    def __init__(self):
        self._jobs: dict[str, ConversionJob] = {}

    def get(self, job_id):
        job = self._jobs.get(job_id)
        return copy.deepcopy(job) if job is not None else None

    def put(self, job):
        clone = copy.deepcopy(job)
        # Shared stores persist `result_key`, not a local path — mimic that
        # so a second manager cannot cheat by opening the producer's file.
        clone.result_path = None
        self._jobs[job.id] = clone

    def list(self, *, owner):
        jobs = [copy.deepcopy(j) for j in self._jobs.values()]
        if owner is None:
            return jobs
        return [j for j in jobs if j.owner == owner]

    def delete(self, job_id):
        job = self._jobs.pop(job_id, None)
        return copy.deepcopy(job) if job is not None else None


class DictResultStore(ResultStore):
    """In-memory blob store with a per-instance cache dir (two-instance sim)."""

    def __init__(self, cache_dir: Path, blobs: dict[str, bytes] | None = None):
        self.cache_dir = cache_dir
        self.blobs = blobs if blobs is not None else {}

    def save(self, job_id, path):
        key = f"conversion-jobs/{job_id}{Path(path).suffix or '.corpus'}"
        self.blobs[key] = Path(path).read_bytes()
        return key

    def save_snapshot(self, job_id, path, label):
        key = f"conversion-jobs/{job_id}/{label}.corpus"
        self.blobs[key] = Path(path).read_bytes()
        return key

    def materialize(self, key, job_id):
        dest = self.cache_dir / Path(key).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.blobs[key])
        return dest

    def delete(self, key):
        self.blobs.pop(key, None)


class TestCopyingStore:
    def test_stall_verdict_persists_for_another_manager(self):
        store = CopyingJobStore()
        manager = make_manager(DeferredExecutor(), store=store, stall_timeout_seconds=10)
        manager.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=lambda: Path("x"), job_id="j1"
        )
        job = store.get("j1")
        job.status = JobStatus.RUNNING
        job.started_at = time.time() - 60
        store.put(job)
        fetched = manager.get("j1")
        assert fetched.status == JobStatus.FAILED
        other = make_manager(DeferredExecutor(), store=store)
        assert other.get("j1").status == JobStatus.FAILED

    def test_logs_and_display_name_survive_terminal_put(self, tmp_path):
        store = CopyingJobStore()
        manager = make_manager(store=store)
        result = tmp_path / "out.corpus"
        result.write_bytes(b"data")

        def work():
            manager.log("j1", "Parsing source...")
            manager.set_display_name("j1", "Summa")
            return result

        manager.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=work, job_id="j1"
        )
        job = manager.get("j1")
        assert job.status == JobStatus.SUCCEEDED
        assert job.logs == ["Parsing source..."]
        assert job.display_name == "Summa"

    def test_two_managers_share_result_bytes(self, tmp_path):
        store = CopyingJobStore()
        blobs: dict[str, bytes] = {}
        producer = make_manager(
            store=store, results=DictResultStore(tmp_path / "a", blobs)
        )
        consumer = make_manager(
            DeferredExecutor(),
            store=store,
            results=DictResultStore(tmp_path / "b", blobs),
        )
        result = tmp_path / "out.corpus"
        result.write_bytes(b"archive-bytes")
        producer.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=lambda: result, job_id="j1"
        )
        job = consumer.get("j1")
        assert job.status == JobStatus.SUCCEEDED
        assert job.result_key == "conversion-jobs/j1.corpus"
        assert job.result_path is None
        assert job.to_dict()["download_ready"] is True
        path = consumer.materialize(job)
        assert path.read_bytes() == b"archive-bytes"
        assert path.parent == tmp_path / "b"

    def test_reap_deletes_remote_result(self, tmp_path):
        store = CopyingJobStore()
        blobs: dict[str, bytes] = {}
        results = DictResultStore(tmp_path / "cache", blobs)
        manager = make_manager(
            DeferredExecutor(), store=store, results=results, retention_seconds=60
        )
        result = tmp_path / "out.corpus"
        result.write_bytes(b"data")
        manager.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=lambda: result, job_id="j1"
        )
        manager._executor.run_all()
        job = manager.get("j1")
        assert job.result_key in blobs
        with manager._lock:
            job = store.get("j1")
            job.finished_at = time.time() - 120
            store.put(job)
        manager.list_jobs(owner=None)
        assert manager.get("j1") is None
        assert blobs == {}


class TestSaveSnapshot:
    def test_local_copies_bytes(self, tmp_path):
        store = LocalResultStore(cache_dir=tmp_path / "cache")
        src = tmp_path / "out.corpus"
        src.write_bytes(b"archive-bytes")
        key = store.save_snapshot("j1", src, "v1.0")
        assert key == "conversion-jobs/j1/v1.0.corpus"
        dest = tmp_path / "cache" / "j1-v1.0.corpus"
        assert dest.read_bytes() == b"archive-bytes"

    def test_local_rejects_unsafe_label(self, tmp_path):
        store = LocalResultStore(cache_dir=tmp_path)
        src = tmp_path / "out.corpus"
        src.write_bytes(b"x")
        assert store.save_snapshot("j1", src, "../etc") is None
        assert store.save_snapshot("j1", src, "v1.0/x") is None
        assert snapshot_key_for("j1", "v1.0") == "conversion-jobs/j1/v1.0.corpus"

    def test_memory_dict_store_copies_bytes(self, tmp_path):
        blobs: dict[str, bytes] = {}
        store = DictResultStore(tmp_path / "cache", blobs)
        src = tmp_path / "out.corpus"
        src.write_bytes(b"archive-bytes")
        key = store.save_snapshot("j1", src, "v1.0")
        assert key == "conversion-jobs/j1/v1.0.corpus"
        assert blobs[key] == b"archive-bytes"

    def test_job_manager_saves_v1_snapshot(self, tmp_path):
        class Recording(LocalResultStore):
            def __init__(self):
                super().__init__(cache_dir=tmp_path / "cache")
                self.snapshots: list[tuple[str, Path, str]] = []

            def save(self, job_id, path):
                return f"conversion-jobs/{job_id}.corpus"

            def save_snapshot(self, job_id, path, label):
                self.snapshots.append((job_id, Path(path), label))
                return super().save_snapshot(job_id, path, label)

        results = Recording()
        manager = make_manager(results=results)
        result = tmp_path / "out.corpus"
        result.write_bytes(b"data")
        job = manager.submit(
            source_format=SourceFormat.PLAIN,
            name="d",
            fn=lambda: result,
            job_id="j1",
        )
        assert manager.get(job.id).status == JobStatus.SUCCEEDED
        assert results.snapshots == [("j1", result, "v1.0")]

    def test_result_save_failure_fails_job(self, tmp_path):
        class BoomSave(LocalResultStore):
            def save(self, job_id, path):
                raise JobStoreError("upload failed")

            def save_snapshot(self, job_id, path, label):
                raise AssertionError("snapshot must not run after save fails")

        manager = make_manager(results=BoomSave())
        result = tmp_path / "out.corpus"
        result.write_bytes(b"data")
        job = manager.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=lambda: result
        )
        fetched = manager.get(job.id)
        assert fetched.status == JobStatus.FAILED
        assert "JobStoreError" in fetched.error

    def test_snapshot_failure_does_not_fail_job(self, tmp_path):
        class BoomSnap(LocalResultStore):
            def save(self, job_id, path):
                return f"conversion-jobs/{job_id}.corpus"

            def save_snapshot(self, job_id, path, label):
                raise RuntimeError("snapshot put failed")

        manager = make_manager(results=BoomSnap())
        result = tmp_path / "out.corpus"
        result.write_bytes(b"data")
        job = manager.submit(
            source_format=SourceFormat.PLAIN, name="d", fn=lambda: result
        )
        fetched = manager.get(job.id)
        assert fetched.status == JobStatus.SUCCEEDED
        assert fetched.error is None
        assert fetched.result_key == f"conversion-jobs/{job.id}.corpus"

    def test_graph_json_is_not_snapshotted(self, tmp_path):
        class Recording(LocalResultStore):
            def __init__(self):
                super().__init__()
                self.snapshots: list[str] = []

            def save(self, job_id, path):
                return f"conversion-jobs/{job_id}.graph.json"

            def save_snapshot(self, job_id, path, label):
                self.snapshots.append(label)
                return None

        results = Recording()
        manager = make_manager(results=results)
        result = tmp_path / "out.graph.json"
        result.write_bytes(b"{}")
        manager.submit(source_format="docx", name="d", fn=lambda: result)
        assert results.snapshots == []


class TestMakeBackends:
    def test_defaults_to_memory_and_local(self, monkeypatch):
        monkeypatch.setattr(settings, "job_store", "memory")
        assert isinstance(make_job_store(), MemoryJobStore)
        assert isinstance(make_result_store(), LocalResultStore)

    def test_supabase_selection(self, monkeypatch):
        monkeypatch.setattr(settings, "job_store", "supabase")
        from admin.services.job_store_supabase import (
            SupabaseJobStore,
            SupabaseResultStore,
        )

        assert isinstance(make_job_store(), SupabaseJobStore)
        assert isinstance(make_result_store(), SupabaseResultStore)
