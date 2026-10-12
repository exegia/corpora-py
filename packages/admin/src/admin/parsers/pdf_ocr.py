"""Shared pinned PDF OCR extraction and auditable page projection."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from ._pdf import PdfParser
from .pdf_progress import WAITING, report, report_page
from .schema import Document, Unit, tokenize

_WORKER = Path(__file__).with_name("pdf_ocr_worker.py")
_OCR_LOCK = threading.Lock()
_OCR_IDLE_SECONDS = 15 * 60


def snapshot_cache_path(source: Path, languages: str, device: str) -> Path:
    from platformdirs import user_cache_path

    root = Path(
        os.environ.get("CORPORA_PDF_OCR_CACHE", str(user_cache_path("corpora") / "pdf-ocr-results"))
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = digest(
        encoded(
            {
                "source": digest(source.read_bytes()),
                "languages": languages,
                "device": device,
                "worker": digest(_WORKER.read_bytes()),
                "lock": digest(_WORKER.with_name("pdf_ocr.lock.json").read_bytes()),
                "runtime": worker_command()[0],
            }
        )
    ).removeprefix("sha256:")
    return root / (key + ".json")


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def worker_command() -> list[str]:
    from platformdirs import user_cache_path

    python = os.environ.get("CORPORA_PDF_OCR_PYTHON", sys.executable)
    models = os.environ.get("CORPORA_PDF_OCR_MODELS", str(user_cache_path("corpora") / "pdf-ocr"))
    return [python, str(_WORKER), "--models", models]


def check_ocr_runtime() -> None:
    try:
        result = subprocess.run(
            worker_command() + ["--check"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(
            "Pinned PDF OCR runtime is unavailable; configure the OCR worker and locked model assets"
        ) from exc
    if result.returncode:
        # Worker deliberately emits user-facing errors; never expose arbitrary
        # tracebacks or private paths from dependency failures through the API.
        reason = result.stderr.strip().splitlines()
        message = (
            reason[-1]
            if reason and reason[-1].startswith(("Pinned PDF OCR", "PDF OCR"))
            else "Pinned PDF OCR runtime is unavailable; configure the locked worker"
        )
        raise ValueError(message)


def inspect_pdf(source: Path) -> int:
    try:
        reader = PdfReader(source, strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF is unsupported; supply an unencrypted document")
        if not reader.pages:
            raise ValueError("PDF contains no pages")
        return len(reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF could not be read; repair it or supply another format") from exc


@dataclass
class PdfOcrResult:
    document: Document
    snapshot: dict
    provenance: dict

    @property
    def pages(self) -> dict[int, str]:
        return {
            int(unit.attrs["page_number"]): "".join(
                token.text + token.after for block in unit.children for token in block.tokens
            )
            for unit in self.document.units
        }


def project_snapshot(
    source: Path, snapshot: dict, provenance: dict, page_count: int
) -> PdfOcrResult:
    if provenance["source_sha256"] != digest(source.read_bytes()):
        raise ValueError("PDF OCR snapshot belongs to a different source revision")
    if provenance["snapshot_sha256"] != digest(encoded(snapshot)):
        raise ValueError("PDF OCR snapshot checksum mismatch")
    doc = snapshot["document"]
    if {int(page) for page in doc["pages"]} != set(range(1, page_count + 1)):
        raise ValueError("PDF OCR page inventory is incomplete; no partial conversion accepted")
    pages = [
        Unit(
            type="page",
            attrs={"id": f"pdf-page-{index}", "page_number": str(index)},
            label=f"Page {index}",
        )
        for index in range(1, page_count + 1)
    ]
    for block in snapshot["blocks"]:
        locations = block["prov"]
        if not locations:
            if block["text"]:
                raise ValueError("PDF OCR text lacks page provenance; source review is required")
            continue
        page_numbers = {loc["page_no"] for loc in locations}
        if len(page_numbers) != 1:
            raise ValueError(
                "PDF OCR block spans multiple pages; explicit source review is required"
            )
        number = page_numbers.pop()
        if number not in range(1, page_count + 1):
            raise ValueError("PDF OCR block refers to an unknown page")
        text = block["text"]
        pages[number - 1].children.append(
            Unit(
                type=block["label"],
                tokens=tokenize(text + ("\n" if text else "")),
                attrs={"docling_ref": block["self_ref"], "provenance": encoded(locations).decode()},
            )
        )
    metadata = PdfParser().parse_metadata(str(source))
    metadata.extra.update(
        {
            "pdf:extraction": "Pinned Docling forced full-page PDF OCR; page blocks use declared newline/table separators",
            "pdf:ocr-provenance": encoded(provenance).decode(),
        }
    )
    return PdfOcrResult(Document(metadata=metadata, units=pages), snapshot, provenance)


def extract_pdf(source: Path) -> PdfOcrResult:
    page_count = inspect_pdf(source)
    languages = os.environ.get("CORPORA_PDF_OCR_LANGUAGES", "eng,heb,grc")
    device = os.environ.get("CORPORA_PDF_OCR_DEVICE", "auto")
    cache = snapshot_cache_path(source, languages, device)
    report(WAITING)
    with _OCR_LOCK, tempfile.TemporaryDirectory(prefix="corpora-pdf-ocr-") as folder:
        if cache.is_file():
            check_ocr_runtime()
            result = json.loads(cache.read_text())
            extraction = project_snapshot(
                source, result["snapshot"], result["provenance"], page_count
            )
            report_page(page_count, page_count)
            report("PDF OCR: reused verified source snapshot; continuing archive validation")
            return extraction
        output = Path(folder) / "result.json"
        command = worker_command() + [
            "--source",
            str(source),
            "--output",
            str(output),
            "--languages",
            languages,
            "--device",
            device,
        ]
        report_page(0, page_count)
        with (Path(folder) / "worker.stderr").open("w+") as errors:
            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=errors, text=True, bufsize=1
                )
            except OSError as exc:
                raise ValueError(
                    "Pinned PDF OCR worker could not start; configure the OCR runtime"
                ) from exc
            events = queue.Queue()

            def read_events():
                try:
                    for line in process.stdout:
                        events.put(line)
                finally:
                    events.put(None)

            reader = threading.Thread(target=read_events, daemon=True)
            reader.start()
            completed = 0
            last_progress = time.monotonic()
            try:
                while True:
                    try:
                        remaining = max(0, _OCR_IDLE_SECONDS - (time.monotonic() - last_progress))
                        line = events.get(timeout=remaining)
                    except queue.Empty as exc:
                        raise ValueError(
                            "Forced PDF OCR stopped after 15 minutes without page progress"
                        ) from exc
                    if line is None:
                        break
                    # Dependency diagnostics can also arrive on stdout.
                    # Only our explicit protocol records count as progress.
                    if not line.startswith("CORPORA_PDF_PROGRESS "):
                        continue
                    event = json.loads(line.removeprefix("CORPORA_PDF_PROGRESS "))
                    if (
                        event["total"] != page_count
                        or not completed <= event["completed"] <= page_count
                    ):
                        raise ValueError("PDF OCR worker reported invalid page progress")
                    if event["completed"] > completed:
                        completed = event["completed"]
                        last_progress = time.monotonic()
                        report_page(completed, page_count)
                process.wait(timeout=30)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                process.stdout.close()
                reader.join(timeout=1)
        if process.returncode or not output.exists():
            raise ValueError(
                "Pinned forced PDF OCR failed; no partial conversion accepted. Check the OCR runtime and try another format if needed"
            )
        result = json.loads(output.read_text())
        # Keep the expensive OCR snapshot even if projection or later source
        # acceptance fails. Retries still verify source/snapshot hashes and
        # the locked runtime; changing code, lock or options changes the key.
        with tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as pending:
            temporary = Path(pending.name)
            pending.write(encoded(result))
        try:
            temporary.replace(cache)
        finally:
            temporary.unlink(missing_ok=True)
    return project_snapshot(source, result["snapshot"], result["provenance"], page_count)
