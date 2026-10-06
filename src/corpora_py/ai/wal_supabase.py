"""Hosted WAL and atomic draft pointers, using server-only Postgres RPCs.

Objects are staged under immutable revision keys before the database publishes
HEAD plus its receipt in one transaction. No legacy upload path is repurposed.
Production archive editing and public endpoint wiring are separate adapters.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

import requests
from pydantic import BaseModel, ConfigDict

from .service import CurationError
from .wal import Intent, Receipt, Record, _validate_plan
from .wal_sqlite import JournalUnavailableError


def _parse[Model: BaseModel](model: type[Model], value: Any) -> Model:
    try:
        return model.model_validate(value)
    except ValueError as exc:
        raise JournalUnavailableError("Hosted change storage unavailable") from exc


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise CurationError(404, "Conversation document or change not found") from exc


class DraftHead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    owner: str
    corpus: str
    bucket: str
    object_key: str
    revision: str
    digest: str
    version: str
    state: Literal["draft", "locked", "published"] = "draft"

    def key_for(self, revision: str) -> str:
        return f"{_uuid(self.owner)}/ai/{_uuid(self.document_id)}/{_uuid(revision)}.corpus"


class HostedStorage:
    def __init__(self, url: str | None, key: str | None, session: Any = None):
        self.url = (url or "").rstrip("/")
        self._key = key
        self._session = session or requests

    def headers(self) -> dict[str, str]:
        if not self.url or not self._key:
            raise JournalUnavailableError("Hosted change storage is not configured")
        return {"apikey": self._key, "Authorization": f"Bearer {self._key}"}

    def rpc(self, action: str, owner: str, payload: dict) -> Any:
        owner = _uuid(owner)
        try:
            response = self._session.post(
                self.url + "/rest/v1/rpc/corpora_ai_storage",
                headers=self.headers(),
                json={"p_action": action, "p_owner": owner, "p_payload": payload},
                timeout=30,
            )
            if response.status_code >= 400:
                # Only exact server-defined errors escape; never forward SQL,
                # URLs, object paths, credentials, or arbitrary upstream bodies.
                body = response.json()
                message = body.get("message") if isinstance(body, dict) else None
                errors = {
                    "AI_NOT_FOUND": (404, "Conversation document or change not found"),
                    "AI_LOCKED": (423, "Corpus is published or locked"),
                    "AI_CONFLICT": (409, "Draft or change conflicts with current state"),
                    "AI_INVALID": (422, "Invalid change storage request"),
                }
                if message in errors:
                    status, detail = errors[message]
                    raise CurationError(status, detail)
                raise JournalUnavailableError("Hosted change storage unavailable")
            return response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise JournalUnavailableError("Hosted change storage unavailable") from exc

    def resolve(self, owner: str, corpus: str) -> DraftHead:
        result = self.rpc("resolve", owner, {"corpus": corpus})
        if result is None:
            raise CurationError(404, "Conversation document not found")
        try:
            head = DraftHead.model_validate(result)
            if head.owner != _uuid(owner) or head.corpus != corpus:
                raise ValueError("Owner mismatch")
            return head
        except ValueError as exc:
            raise JournalUnavailableError("Hosted change storage unavailable") from exc

    def register(self, head: DraftHead) -> DraftHead:
        """Trusted provisioning only: verify source ownership outside this method.

        The initial immutable object must already be uploaded and verified. This
        method is intentionally not exposed to HTTP/MCP or automatic lookup.
        """
        self.verify_object(head, head.object_key, head.digest)
        result = self.rpc("register", head.owner, head.model_dump(exclude={"owner", "state"}))
        return _parse(DraftHead, result)

    def set_state(
        self, owner: str, corpus: str, state: Literal["draft", "locked", "published"]
    ) -> DraftHead:
        """Trusted lifecycle hook, serialized with every publication."""
        return _parse(DraftHead, self.rpc("set_state", owner, {"corpus": corpus, "state": state}))

    def receipt(self, owner: str, operation_id: str) -> Receipt | None:
        result = self.rpc("receipt", owner, {"id": _uuid(operation_id)})
        return _parse(Receipt, result) if result is not None else None

    def publish(self, intent: Intent) -> bool:
        head = self.resolve(intent.owner, intent.suggestion.scope.corpus)
        if head.state != "draft":
            raise CurationError(423, "Corpus is published or locked")
        object_key = head.key_for(intent.plan.after.revision)
        self.verify_object(head, object_key, intent.plan.after.digest)
        result = self.rpc(
            "publish",
            intent.owner,
            {"id": _uuid(intent.id), "proof": intent.proof, "object_key": object_key},
        )
        if not isinstance(result, bool):
            raise JournalUnavailableError("Hosted change storage unavailable")
        return result

    def _object_url(self, head: DraftHead, object_key: str) -> str:
        # Only the dedicated private bucket and owner/document revision subtree
        # may be used. No arbitrary URL/path can be supplied by an API caller.
        prefix = f"{_uuid(head.owner)}/ai/{_uuid(head.document_id)}/"
        if head.bucket != "corpus-ai-drafts" or not object_key.startswith(prefix):
            raise CurationError(422, "Invalid immutable draft location")
        revision = object_key[len(prefix) :].removesuffix(".corpus")
        if object_key != head.key_for(revision):
            raise CurationError(422, "Invalid immutable draft location")
        return (
            self.url
            + "/storage/v1/object/"
            + quote(head.bucket, safe="")
            + "/"
            + quote(object_key, safe="/")
        )

    def download(self, head: DraftHead, destination: Path) -> None:
        """Download only a resolved immutable head and verify its complete bytes."""
        try:
            with self._session.get(
                self._object_url(head, head.object_key),
                headers=self.headers(),
                timeout=60,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise JournalUnavailableError("Registered draft is unavailable")
                hasher = hashlib.sha256()
                with destination.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        output.write(chunk)
                        hasher.update(chunk)
            if "sha256:" + hasher.hexdigest() != head.digest:
                destination.unlink(missing_ok=True)
                raise CurationError(409, "Registered draft digest mismatch")
        except (requests.RequestException, OSError) as exc:
            destination.unlink(missing_ok=True)
            raise JournalUnavailableError("Registered draft is unavailable") from exc

    def verify_object(self, head: DraftHead, object_key: str, expected_digest: str) -> None:
        """Read back bytes: a successful upload alone is not publication proof."""
        try:
            with self._session.get(
                self._object_url(head, object_key), headers=self.headers(), timeout=60, stream=True
            ) as response:
                if response.status_code != 200:
                    raise JournalUnavailableError("Staged draft is unavailable")
                digest = hashlib.sha256()
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    digest.update(chunk)
            if "sha256:" + digest.hexdigest() != expected_digest:
                raise CurationError(409, "Staged draft digest mismatch")
        except (requests.RequestException, OSError) as exc:
            raise JournalUnavailableError("Staged draft is unavailable") from exc

    def stage(self, head: DraftHead, revision: str, archive: Path, expected_digest: str) -> str:
        object_key = head.key_for(revision)
        try:
            with archive.open("rb") as source:
                actual = "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()
                if actual != expected_digest:
                    raise CurationError(409, "Prepared draft digest mismatch")
                source.seek(0)
                response = self._session.post(
                    self._object_url(head, object_key),
                    headers={
                        **self.headers(),
                        "Content-Type": "application/zip",
                        "x-upsert": "false",
                    },
                    data=source,
                    timeout=60,
                )
            # Supabase can return 400 or 409 for a duplicate key. Do not parse
            # messages or overwrite: exact read-back digest is the retry proof.
            if response.status_code not in (200, 201, 400, 409):
                raise JournalUnavailableError("Staged draft upload failed")
            self.verify_object(head, object_key, expected_digest)
            return object_key
        except (requests.RequestException, OSError) as exc:
            raise JournalUnavailableError("Staged draft upload failed") from exc


class SupabaseJournal:
    def __init__(self, storage: HostedStorage):
        self.storage = storage

    @staticmethod
    def _record(value: Any) -> Record:
        try:
            return Record.model_validate(value)
        except ValueError as exc:
            raise JournalUnavailableError("Hosted change storage unavailable") from exc

    def get(self, owner: str, operation_id: str) -> Record | None:
        value = self.storage.rpc("get", owner, {"id": _uuid(operation_id)})
        record = self._record(value) if value is not None else None
        if record and (
            record.intent.owner != _uuid(owner) or record.intent.id != _uuid(operation_id)
        ):
            raise JournalUnavailableError("Hosted change storage unavailable")
        return record

    def insert(self, intent: Intent) -> Record:
        _validate_plan(intent.suggestion, intent.plan)
        value = self.storage.rpc(
            "insert",
            intent.owner,
            {
                "intent": intent.model_dump(mode="json"),
                "proof": intent.proof,
                "entries": [e.model_dump(mode="json") for e in intent.entries(intent.created_at)],
            },
        )
        record = self._record(value)
        if record.intent.owner != intent.owner or record.intent.id != intent.id:
            raise JournalUnavailableError("Hosted change storage unavailable")
        return record

    def finish(self, owner: str, operation_id: str, applied_at: datetime) -> Record:
        # The database takes its timestamp from the atomic publication receipt;
        # the caller cannot forge a time or finalize an unpublished operation.
        return self._record(self.storage.rpc("finish", owner, {"id": _uuid(operation_id)}))

    def pending(self, owner: str, limit: int = 100) -> list[Record]:
        if not 1 <= limit <= 100:
            raise CurationError(422, "Pending batch limit must be between 1 and 100")
        rows = self.storage.rpc("pending", owner, {"limit": limit})
        if not isinstance(rows, list):
            raise JournalUnavailableError("Hosted change storage unavailable")
        records = [self._record(row) for row in rows]
        if any(record.intent.owner != _uuid(owner) for record in records):
            raise JournalUnavailableError("Hosted change storage unavailable")
        return records
