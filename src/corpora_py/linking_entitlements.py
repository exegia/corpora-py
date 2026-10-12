"""Explicit admin synchronization of trusted inventory entitlements, outside core."""

import hashlib
import json
from uuid import UUID

import psycopg
from corpora_linking import Endpoint
from corpora_linking.models import NonEmpty, Value
from psycopg.types.json import Jsonb
from pydantic import model_validator

from .linking_access import endpoint_scope
from .linking_postgres import PostgreSQLReferenceStore
from .linking_store import VersionConflictError


class EntitlementSnapshot(Value):
    """Complete desired grants for one space/user, supplied by a trusted provider.

    Explicit pinned inventory entries only. No ownership/visibility is inferred
    from corpus names, paths, JWT metadata or unverified caller assertions.
    """

    provider_id: NonEmpty
    provider_revision: NonEmpty
    resources: tuple[Endpoint, ...]

    @model_validator(mode="after")
    def exact_scopes(self) -> "EntitlementSnapshot":
        keys = []
        for endpoint in self.resources:
            if endpoint.locators:
                raise ValueError("entitlement resources must be scopes without locators")
            keys.append(endpoint_scope(endpoint)[0])
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate entitlement scopes")
        return self

    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        payload["resources"] = sorted(
            payload["resources"], key=lambda item: json.dumps(item, sort_keys=True)
        )
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


class PostgreSQLEntitlementSynchronizer:
    """Trusted admin-only complete replacement; never bind directly to a client body.

    One configured provider owns the entire grant set for a target user/space.
    The application must fetch/validate provider evidence before invoking sync.
    Existing grants are adopted explicitly on first synchronization, then replaced.
    """

    def __init__(self, store: PostgreSQLReferenceStore, *, provider_id: str):
        if not provider_id.strip():
            raise ValueError("provider_id is required")
        self.store = store
        self.provider_id = provider_id

    def synchronize(
        self, user_id: UUID, snapshot: EntitlementSnapshot, *, expected_version: int | None
    ) -> int:
        snapshot = EntitlementSnapshot.model_validate(snapshot.model_dump())
        if snapshot.provider_id != self.provider_id:
            raise ValueError("entitlement provider differs from configured authority")
        if expected_version is not None and (
            type(expected_version) is not int or expected_version < 1
        ):
            raise ValueError("expected_version must be positive or None for adoption")
        digest = snapshot.digest()
        with psycopg.connect(self.store.dsn) as db:
            self.store._authorize(db, "admin")
            # Same per-user lock serializes initial creation and subsequent sync.
            key = int.from_bytes(
                hashlib.sha256(f"entitlements/{self.store.space_id}/{user_id}".encode()).digest()[
                    :8
                ],
                "big",
                signed=True,
            )
            db.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            members = db.execute(
                "SELECT capability FROM reference_working.memberships WHERE space_id = %s AND user_id = %s FOR SHARE",
                (self.store.space_id, user_id),
            ).fetchall()
            if not members:
                raise PermissionError("target user must belong to the reference space")
            row = db.execute(
                "SELECT version, provider_id, digest FROM reference_working.entitlement_heads WHERE space_id = %s AND user_id = %s FOR UPDATE",
                (self.store.space_id, user_id),
            ).fetchone()
            if row and row[1] != self.provider_id:
                raise ValueError("grant set belongs to another provider")
            actual = row[0] if row else None
            if actual != expected_version:
                raise VersionConflictError("entitlement version changed")
            existing = db.execute(
                "SELECT resource_key, scope FROM reference_working.resource_access "
                "WHERE space_id = %s AND user_id = %s ORDER BY resource_key FOR UPDATE",
                (self.store.space_id, user_id),
            ).fetchall()
            desired = dict(endpoint_scope(endpoint) for endpoint in snapshot.resources)
            if row and row[2] == digest and dict(existing) == desired:
                return int(row[0])
            # DELETE locks existing rows, serializing with in-flight resource reads.
            db.execute(
                "DELETE FROM reference_working.resource_access WHERE space_id = %s AND user_id = %s",
                (self.store.space_id, user_id),
            )
            for endpoint in sorted(
                snapshot.resources, key=lambda endpoint: endpoint_scope(endpoint)[0]
            ):
                resource_key, scope = endpoint_scope(endpoint)
                db.execute(
                    "INSERT INTO reference_working.resource_access VALUES (%s, %s, %s, %s)",
                    (self.store.space_id, user_id, resource_key, Jsonb(scope)),
                )
            version = (actual or 0) + 1
            db.execute(
                "INSERT INTO reference_working.entitlement_heads VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (space_id, user_id) DO UPDATE SET version = EXCLUDED.version, provider_revision = EXCLUDED.provider_revision, digest = EXCLUDED.digest, record = EXCLUDED.record",
                (
                    self.store.space_id,
                    user_id,
                    version,
                    self.provider_id,
                    snapshot.provider_revision,
                    digest,
                    Jsonb(snapshot.model_dump(mode="json")),
                ),
            )
            return version
