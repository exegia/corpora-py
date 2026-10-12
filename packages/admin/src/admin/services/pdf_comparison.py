"""Independent visual OCR orchestration, checkpoint integrity and agreement."""

import hashlib
import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

from platformdirs import user_cache_path

from ..parsers.pdf_progress import WAITING_COMPARISON, report

ROOT = Path(__file__).parents[1] / "parsers"
WORKER = ROOT / "pdf_comparison_worker.py"
LOCK = ROOT / "pdf_comparison.lock.json"
_LOCK = threading.Lock()
IDLE_SECONDS = 15 * 60
PREFIX = "CORPORA_COMPARISON_PROGRESS "


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def comparison_cache(source, python, models, binary):
    root = Path(os.environ.get("CORPORA_PDF_COMPARISON_CACHE", user_cache_path("corpora") / "pdf-comparison"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = digest(encoded({
        "source": digest(source.read_bytes()), "worker": digest(WORKER.read_bytes()),
        "lock": digest(LOCK.read_bytes()), "python": python,
        "models": str(models), "binary": str(binary),
    })).removeprefix("sha256:")
    return root / (key + ".json")


def read_snapshot(path, source_hash):
    payload = json.loads(path.read_text())
    snapshot = payload["snapshot"]
    if payload["snapshot_sha256"] != digest(encoded(snapshot)):
        raise ValueError("Independent visual OCR snapshot checksum mismatch")
    if snapshot["source_sha256"] != source_hash or snapshot["lock_sha256"] != digest(LOCK.read_bytes()):
        raise ValueError("Independent visual OCR snapshot revision mismatch")
    return payload


def export_comparison_evidence(source: Path, report: dict) -> tuple[dict, bytes]:
    """Return the exact completed evidence that produced this assessment."""
    python = os.environ["CORPORA_PDF_COMPARISON_PYTHON"]
    models = Path(os.environ["CORPORA_PDF_COMPARISON_MODELS"])
    binary = Path(os.environ["CORPORA_PDF_COMPARISON_BINARY"])
    cache = comparison_cache(source, python, models, binary)
    payload = read_snapshot(cache, report["source_sha256"])
    snapshot = payload["snapshot"]
    if (
        payload["snapshot_sha256"] != report["comparison_snapshot_sha256"]
        or snapshot["page_count"] != report["compared_pages"]
        or set(snapshot["pages"]) != {str(i) for i in range(1, snapshot["page_count"] + 1)}
    ):
        raise ValueError("Independent OCR export evidence differs from the completed comparison")
    lock = LOCK.read_bytes()
    if digest(lock) != report["comparison_lock_sha256"]:
        raise ValueError("Independent OCR export lock revision mismatch")
    return payload, lock


def run_worker(source, cache, python, models, binary):
    with tempfile.TemporaryFile(mode="w+") as errors:
        process = subprocess.Popen(
            [python, str(WORKER), "--source", str(source), "--output", str(cache),
             "--models", str(models), "--binary", str(binary)],
            stdout=subprocess.PIPE, stderr=errors, text=True, start_new_session=os.name != "nt",
        )
        lines = queue.Queue()

        def consume():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        last_progress = time.monotonic()
        completed = 0
        try:
            while True:
                remaining = IDLE_SECONDS - (time.monotonic() - last_progress)
                if remaining <= 0:
                    raise ValueError("Independent visual comparison stopped after 15 minutes without page progress; retry resumes cached pages")
                try:
                    line = lines.get(timeout=remaining)
                except queue.Empty as exc:
                    raise ValueError("Independent visual comparison stopped after 15 minutes without page progress; retry resumes cached pages") from exc
                if line is None:
                    break
                if not line.startswith(PREFIX):
                    continue
                event = json.loads(line[len(PREFIX):])
                if not completed <= event["completed"] <= event["total"]:
                    raise ValueError("Independent comparison emitted invalid page progress")
                completed = event["completed"]
                last_progress = time.monotonic()
                report(f"Independent visual comparison: completed {completed}/{event['total']} pages")
            if process.wait(timeout=30):
                raise ValueError("Independent visual OCR comparison failed; completed pages are cached. Check its runtime and retry")
        finally:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.terminate()
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
            process.stdout.close()
            reader.join(timeout=1)


def automatic_comparison(source, evidence):
    from .source_reliability import compare_verified_pages

    python = os.environ.get("CORPORA_PDF_COMPARISON_PYTHON")
    models_value = os.environ.get("CORPORA_PDF_COMPARISON_MODELS")
    binary_value = os.environ.get("CORPORA_PDF_COMPARISON_BINARY")
    if not all((python, models_value, binary_value)):
        raise ValueError("Automatic visual comparison runtime is not configured; set CORPORA_PDF_COMPARISON_PYTHON, MODELS and BINARY")
    models, binary = Path(models_value), Path(binary_value)
    cache = comparison_cache(source, python, models, binary)
    report(WAITING_COMPARISON)
    with _LOCK:
        payload = read_snapshot(cache, evidence["source_sha256"]) if cache.is_file() else None
        if payload is None or set(payload["snapshot"]["pages"]) != set(evidence["converted_pages"]):
            report("Starting independent visual OCR of original PDF pixels...")
            run_worker(source, cache, python, models, binary)
            payload = read_snapshot(cache, evidence["source_sha256"])
        else:
            report("Independent visual comparison: reused verified pixel-OCR snapshot")
    snapshot = payload["snapshot"]
    if set(snapshot["pages"]) != {str(i) for i in range(1, snapshot["page_count"] + 1)}:
        raise ValueError("Independent visual comparison page inventory is incomplete")

    def normalize(text):
        # Layout engines introduce different line/paragraph separators. Keep
        # boundaries between words and all Greek/Hebrew marks and word order.
        return " ".join(unicodedata.normalize("NFD", text).split())

    expected = {page: normalize(item["text"]) for page, item in snapshot["pages"].items()}
    actual = {page: normalize(text) for page, text in evidence["converted_pages"].items()}
    report("Computing independent OCR agreement and page mismatches...")
    result = compare_verified_pages(expected, actual)
    result.update(
        source_sha256=evidence["source_sha256"], snapshot_sha256=evidence["snapshot_sha256"],
        complete=True, method="independent-visual-ocr-agreement/v2",
        assessment_kind="automatic-ocr-agreement", comparison_engine="Surya OCR 2 (0.22.1)",
        comparison_snapshot_sha256=payload["snapshot_sha256"],
        comparison_lock_sha256=snapshot["lock_sha256"],
        comparison_model_revision=snapshot["models"]["revision"],
        compared_pages=snapshot["page_count"],
        normalization="NFD canonical equivalence; whitespace runs collapsed; word boundaries, order and script marks compared",
    )
    return result
