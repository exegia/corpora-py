"""Explicit single-host durable journal for the write-ahead engine.

Not a fallback for Supabase. No public routes select this backend yet. Hosted
integration must adapt the existing corpus_changes table transactionally.
"""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .wal import Intent, Record


class JournalUnavailableError(Exception):
    """Safe boundary error; callers must not publish when insert fails."""


class SQLiteJournal:
    def __init__(self, path: Path | str):
        if str(path) == ":memory:":
            raise ValueError("The write-ahead journal requires a durable file")
        self.path = Path(path).expanduser()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS ai_change_intents (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    reverts TEXT UNIQUE, intent TEXT NOT NULL CHECK(json_valid(intent)),
                    applied_at TEXT)""")
                connection.commit()
            self.path.chmod(0o600)
        except (OSError, sqlite3.Error) as exc:
            raise JournalUnavailableError("Change journal unavailable") from exc

    def _query(self, sql: str, params: tuple) -> Record | None:
        try:
            with closing(sqlite3.connect(self.path, timeout=15)) as connection:
                # FULL is required for an acknowledged intent to survive a crash.
                connection.execute("PRAGMA synchronous=FULL")
                row = connection.execute(sql, params).fetchone()
                connection.commit()
            if row is None:
                return None
            return Record(intent=Intent.model_validate_json(row[0]), applied_at=row[1])
        except (sqlite3.Error, ValueError) as exc:
            raise JournalUnavailableError("Change journal unavailable") from exc

    def get(self, owner: str, operation_id: str) -> Record | None:
        return self._query(
            "SELECT intent,applied_at FROM ai_change_intents WHERE owner=? AND id=?",
            (owner, operation_id),
        )

    def insert(self, intent: Intent) -> Record:
        self._query(
            """INSERT INTO ai_change_intents(id,owner,reverts,intent)
            VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING RETURNING intent,applied_at""",
            (intent.id, intent.owner, intent.reverts, intent.model_dump_json()),
        )
        record = self.get(intent.owner, intent.id)
        if record is None:
            raise JournalUnavailableError("Change journal unavailable")
        return record

    def finish(self, owner: str, operation_id: str, applied_at: datetime) -> Record:
        record = self._query(
            """UPDATE ai_change_intents
            SET applied_at=COALESCE(applied_at,?) WHERE owner=? AND id=?
            RETURNING intent,applied_at""",
            (applied_at.isoformat(), owner, operation_id),
        )
        if record is None:
            raise JournalUnavailableError("Change journal unavailable")
        return record
