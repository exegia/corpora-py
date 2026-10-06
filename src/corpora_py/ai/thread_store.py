"""Durable conversation aggregates with optimistic, atomic updates.

One row holds a thread and its append-only sections/messages plus suggestion
states. Compare-and-swap prevents lost updates across API instances. The
bounded aggregate keeps fork/message/suggestion changes in one transaction;
corpus edits and their write-ahead log remain separate (#234).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field

from .schemas import Thread, ThreadMessage, ThreadSuggestion


class ThreadState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread: Thread
    messages: list[ThreadMessage] = Field(default_factory=list)
    suggestions: list[ThreadSuggestion] = Field(default_factory=list)


class ThreadRecord(BaseModel):
    id: str
    owner: str
    corpus: str
    created_at: str
    revision: int = 0
    data: ThreadState


class ThreadStoreError(Exception):
    """Backend failures must not expose keys, URLs, SQL, or response bodies."""


class ThreadStore(Protocol):
    def get(self, owner: str, thread_id: str) -> ThreadRecord | None: ...
    def create(self, record: ThreadRecord) -> bool: ...
    def replace(self, record: ThreadRecord) -> bool: ...
    def list(
        self, owner: str, corpus: str, limit: int, before: tuple[str, str] | None = None
    ) -> list[ThreadRecord]: ...


class SQLiteThreadStore:
    """Persistent single-host backend. A fresh connection per operation."""

    def __init__(self, path: str | Path):
        if str(path) == ":memory:":
            raise ValueError("AI SQLite storage requires a durable file path")
        self.path = Path(path).expanduser()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS ai_threads (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, corpus TEXT NOT NULL,
                    created_at TEXT NOT NULL, revision INTEGER NOT NULL,
                    data TEXT NOT NULL CHECK(json_valid(data)))""")
                connection.execute("""CREATE INDEX IF NOT EXISTS ai_threads_owner_corpus_created
                    ON ai_threads(owner, corpus, created_at DESC, id DESC)""")
                connection.commit()
            self.path.chmod(0o600)
        except (OSError, sqlite3.Error) as exc:
            raise ThreadStoreError("Conversation storage unavailable") from exc

    def _query(self, sql: str, params: tuple = ()) -> list[ThreadRecord]:
        try:
            with closing(sqlite3.connect(self.path, timeout=15)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(sql, params).fetchall()
                connection.commit()
            return [ThreadRecord(**{**dict(row), "data": json.loads(row["data"])}) for row in rows]
        except (sqlite3.Error, ValueError) as exc:
            raise ThreadStoreError("Conversation storage unavailable") from exc

    def get(self, owner: str, thread_id: str) -> ThreadRecord | None:
        rows = self._query("SELECT * FROM ai_threads WHERE owner=? AND id=?", (owner, thread_id))
        return rows[0] if rows else None

    def create(self, record: ThreadRecord) -> bool:
        rows = self._query(
            """INSERT INTO ai_threads(id,owner,corpus,created_at,revision,data)
            VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING RETURNING *""",
            (
                record.id,
                record.owner,
                record.corpus,
                record.created_at,
                0,
                record.data.model_dump_json(),
            ),
        )
        return bool(rows)

    def replace(self, record: ThreadRecord) -> bool:
        rows = self._query(
            """UPDATE ai_threads SET data=?, revision=revision+1
            WHERE owner=? AND id=? AND revision=? RETURNING *""",
            (record.data.model_dump_json(), record.owner, record.id, record.revision),
        )
        return bool(rows)

    def list(
        self, owner: str, corpus: str, limit: int, before: tuple[str, str] | None = None
    ) -> list[ThreadRecord]:
        where = " AND (created_at,id) < (?,?)" if before else ""
        return self._query(
            "SELECT * FROM ai_threads WHERE owner=? AND corpus=?"
            + where
            + " ORDER BY created_at DESC,id DESC LIMIT ?",
            (owner, corpus, *(before or ()), limit),
        )


class SupabaseThreadStore:
    """PostgREST backend. Every read/update includes the verified owner filter."""

    def __init__(self, url: str | None, key: str | None, session: Any = None):
        self.url = (url or "").rstrip("/")
        self._key = key
        self._session = session or requests

    def _request(
        self,
        method: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
        create: bool = False,
    ) -> list[ThreadRecord]:
        if not self.url or not self._key:
            raise ThreadStoreError("Conversation storage is not configured")
        try:
            response = self._session.request(
                method,
                self.url + "/rest/v1/corpus_ai_threads",
                params=params,
                json=body,
                timeout=30,
                headers={
                    "apikey": self._key,
                    "Authorization": f"Bearer {self._key}",
                    "Prefer": "return=representation"
                    + (",resolution=ignore-duplicates" if create else ""),
                },
            )
            if response.status_code >= 400:
                raise ThreadStoreError("Conversation storage unavailable")
            return [ThreadRecord.model_validate(row) for row in response.json()]
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise ThreadStoreError("Conversation storage unavailable") from exc

    def get(self, owner: str, thread_id: str) -> ThreadRecord | None:
        rows = self._request(
            "GET", params={"owner": f"eq.{owner}", "id": f"eq.{thread_id}", "limit": "1"}
        )
        return rows[0] if rows else None

    def create(self, record: ThreadRecord) -> bool:
        return bool(
            self._request(
                "POST",
                params={"on_conflict": "id"},
                body=record.model_dump(mode="json"),
                create=True,
            )
        )

    def replace(self, record: ThreadRecord) -> bool:
        return bool(
            self._request(
                "PATCH",
                params={
                    "owner": f"eq.{record.owner}",
                    "id": f"eq.{record.id}",
                    "revision": f"eq.{record.revision}",
                },
                body={"revision": record.revision + 1, "data": record.data.model_dump(mode="json")},
            )
        )

    def list(
        self, owner: str, corpus: str, limit: int, before: tuple[str, str] | None = None
    ) -> list[ThreadRecord]:
        params = {
            "owner": f"eq.{owner}",
            "corpus": f"eq.{corpus}",
            "order": "created_at.desc,id.desc",
            "limit": str(limit),
        }
        if before:
            # Cursor components have been normalized to datetime/UUID by the service.
            timestamp, thread_id = before
            params["or"] = (
                f"(created_at.lt.{timestamp},and(created_at.eq.{timestamp},id.lt.{thread_id}))"
            )
        return self._request("GET", params=params)
