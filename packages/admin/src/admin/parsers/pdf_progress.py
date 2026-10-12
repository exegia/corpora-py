"""Thread-scoped PDF progress and timestamped events stored in existing job logs."""

import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_REPORTER = ContextVar("pdf_progress_reporter", default=None)
WAITING = "PDF OCR: waiting for worker"
WAITING_COMPARISON = "PDF comparison: waiting for independent worker"
WAITING_STAGES = {WAITING, WAITING_COMPARISON}
_ACTIVITY = re.compile(r"^PDF OCR: (worker started|completed (\d+)/(\d+) pages) at (\S+)$")
_STAGE_ACTIVITY = re.compile(r"^.* \[updated (\S+)\]$")


def stamp_activity(message):
    if message in WAITING_STAGES or _ACTIVITY.fullmatch(message):
        return message
    return f"{message} [updated {datetime.now(UTC).isoformat(timespec='milliseconds')}]"


@contextmanager
def report_pdf_progress(callback):
    token = _REPORTER.set(callback)
    try:
        yield
    finally:
        _REPORTER.reset(token)


def report(message):
    callback = _REPORTER.get()
    if callback is not None:
        callback(message)


def report_page(completed, total):
    message = "worker started" if completed == 0 else f"completed {completed}/{total} pages"
    report(f"PDF OCR: {message} at {datetime.now(UTC).isoformat(timespec='milliseconds')}")


def latest_activity(logs):
    """Return only real worker/page events; status polling is not progress."""
    for line in reversed(logs):
        match = _ACTIVITY.fullmatch(line)
        stage = _STAGE_ACTIVITY.fullmatch(line)
        if match or stage:
            try:
                updated = datetime.fromisoformat(match[4] if match else stage[1])
                if updated.tzinfo is None:
                    continue
                return {
                    "completed_pages": int(match[2] or 0) if match else 0,
                    "total_pages": int(match[3]) if match and match[3] else None,
                    "updated_at": updated.timestamp(),
                }
            except ValueError:
                continue
    return None
