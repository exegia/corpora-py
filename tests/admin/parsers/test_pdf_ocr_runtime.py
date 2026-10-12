"""Worker progress, idle termination, page boundaries and verified retry cache."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from admin.parsers import pdf_ocr
from admin.parsers.pdf_ocr_worker import page_bounded_merges
from admin.parsers.pdf_progress import report_pdf_progress

FIXTURES = Path(__file__).parents[1] / "fixtures/cusx"


def test_merge_prediction_never_joins_page_continuations():
    elements = [
        SimpleNamespace(page_no=1, cid=1),
        SimpleNamespace(page_no=1, cid=2),
        SimpleNamespace(page_no=2, cid=3),
        SimpleNamespace(page_no=2, cid=4),
    ]
    observed = []

    def predict(*, sorted_elements):
        observed.append([element.page_no for element in sorted_elements])
        return {sorted_elements[0].cid: [element.cid for element in sorted_elements[1:]]}

    assert page_bounded_merges(predict, elements) == {1: [2], 3: [4]}
    assert observed == [[1, 1], [2, 2]]


def fake_worker(tmp_path, monkeypatch, *, stall=False):
    worker = tmp_path / "worker.py"
    script = f"""import argparse, json, time
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--output')
args,_=p.parse_known_args()
counter=Path({str(tmp_path / "runs")!r})
counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')
print("CORPORA_PDF_PROGRESS " + json.dumps({{"completed":0,"total":2}}),flush=True)
"""
    if stall:
        script += "time.sleep(60)\n"
    else:
        script += f"""print("CORPORA_PDF_PROGRESS " + json.dumps({{"completed":1,"total":2}}),flush=True)
print("Dependency diagnostic: 2026 stdout text is not a progress record")
print("CORPORA_PDF_PROGRESS " + json.dumps({{"completed":2,"total":2}}),flush=True)
Path(args.output).write_text(Path({str(FIXTURES / "docling-forced-ocr.json")!r}).read_text())
"""
    worker.write_text(script)
    worker.with_name("pdf_ocr.lock.json").write_text("{}")
    monkeypatch.setattr(pdf_ocr, "_WORKER", worker)
    monkeypatch.setattr(pdf_ocr, "worker_command", lambda: [sys.executable, str(worker)])
    monkeypatch.setattr(pdf_ocr, "check_ocr_runtime", lambda: None)
    monkeypatch.setenv("CORPORA_PDF_OCR_CACHE", str(tmp_path / "cache"))


def test_streamed_pages_and_cached_retry_keep_exact_snapshot(tmp_path, monkeypatch):
    fake_worker(tmp_path, monkeypatch)
    logs = []
    with report_pdf_progress(logs.append):
        first = pdf_ocr.extract_pdf(FIXTURES / "outlined.pdf")
        second = pdf_ocr.extract_pdf(FIXTURES / "outlined.pdf")
    assert first.snapshot == second.snapshot
    assert first.provenance == second.provenance
    assert (tmp_path / "runs").read_text() == "1"
    assert any("completed 1/2 pages" in line for line in logs)
    assert "reused verified source snapshot" in logs[-1]
    # A changed runtime/worker must not reuse an earlier snapshot.
    worker = tmp_path / "worker.py"
    worker.write_text(worker.read_text() + "\n# new worker revision\n")
    pdf_ocr.extract_pdf(FIXTURES / "outlined.pdf")
    assert (tmp_path / "runs").read_text() == "2"


def test_cached_snapshot_tampering_is_rejected(tmp_path, monkeypatch):
    fake_worker(tmp_path, monkeypatch)
    pdf_ocr.extract_pdf(FIXTURES / "outlined.pdf")
    cache = next((tmp_path / "cache").glob("*.json"))
    payload = json.loads(cache.read_text())
    payload["snapshot"]["blocks"][0]["text"] = "corrupted"
    cache.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="checksum mismatch"):
        pdf_ocr.extract_pdf(FIXTURES / "outlined.pdf")


def test_idle_worker_is_terminated(tmp_path, monkeypatch):
    fake_worker(tmp_path, monkeypatch, stall=True)
    monkeypatch.setattr(pdf_ocr, "_OCR_IDLE_SECONDS", 0.2)
    processes = []
    original_popen = pdf_ocr.subprocess.Popen

    def spawn(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(pdf_ocr.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="without page progress"):
        pdf_ocr.extract_pdf(FIXTURES / "outlined.pdf")
    assert processes and processes[0].poll() is not None
    assert not list((tmp_path / "cache").glob("*.json"))
