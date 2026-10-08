"""Optional PostgreSQL working store; no schema creation or production routing."""

from typing import Literal
from uuid import UUID

import psycopg
from common.utils.jwt_auth import AuthError, verify_jwt
from corpora_linking import Reference
from psycopg.types.json import Jsonb

from .linking_conversion import ConvertedReference
from .linking_store import (
    SQLiteReferenceStore,
    ValidationReport,
    VersionConflictError,
    WorkingRevision,
    prepare_revision,
)


class PostgreSQLReferenceStore(SQLiteReferenceStore):
    """Server-only adapter constructed from a verified JWT, never a claimed actor.

    Requires the separately provisioned private schema. Each operation opens its
    own connection and rechecks current membership. The caller supplies trusted
    configuration; do not expose DSNs, JWKS settings or space choices without
    application authorization. No conversion/publication ledger is implemented.
    """

    def __init__(self, dsn: str, *, space_id: UUID, token: str, jwks_url: str, audience: str):
        # Verify before opening a privileged database connection. Reverify for
        # every operation so a long-lived adapter cannot retain expired access.
        self.dsn = dsn
        self.space_id = space_id
        self._token = token
        self._jwks_url = jwks_url
        self._audience = audience
        self.actor_id = str(self._principal())

    def _principal(self) -> UUID:
        claims = verify_jwt(self._token, jwks_url=self._jwks_url, audience=self._audience)
        try:
            return UUID(claims["sub"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise AuthError("JWT requires a UUID subject") from exc

    def _authorize(self, db: psycopg.Connection, capability: str | None) -> UUID:
        actor = self._principal()
        rows = db.execute(
            "SELECT capability FROM reference_working.memberships "
            "WHERE space_id = %s AND user_id = %s FOR SHARE",
            (self.space_id, actor),
        ).fetchall()
        capabilities = {row[0] for row in rows}
        if not capabilities or (
            capability is not None
            and capability not in capabilities
            and "admin" not in capabilities
        ):
            raise PermissionError("reference space capability required")
        return actor

    def history(self, reference_id: UUID) -> tuple[WorkingRevision, ...]:
        with psycopg.connect(self.dsn) as db:
            self._authorize(db, None)
            rows = db.execute(
                "SELECT version, actor_id, recorded_at, reason, action, reference, validation, conversion "
                "FROM reference_working.revisions WHERE space_id = %s AND reference_id = %s "
                "ORDER BY version",
                (self.space_id, reference_id),
            ).fetchall()
            return tuple(self._decode(row) for row in rows)

    @staticmethod
    def _decode(row: tuple) -> WorkingRevision:
        return WorkingRevision.model_validate(
            dict(
                zip(
                    (
                        "version",
                        "actor_id",
                        "recorded_at",
                        "reason",
                        "action",
                        "reference",
                        "validation",
                        "conversion",
                    ),
                    (row[0], str(row[1]), *row[2:]),
                    strict=True,
                )
            )
        )

    def _write(
        self,
        reference: Reference,
        *,
        expected_version: int | None,
        reason: str,
        action: Literal["edit", "resolve", "approve", "reject", "publish", "withdraw", "reopen"],
        validation: ValidationReport | None = None,
        conversion: ConvertedReference | None = None,
    ) -> int:
        if expected_version is not None and (
            type(expected_version) is not int or expected_version < 1
        ):
            raise ValueError("expected_version must be a positive integer or None for creation")
        if action in ("publish", "withdraw"):
            raise ValueError("publication requires a separate ledger adapter")
        capability = "review" if action in ("approve", "reject") else "contribute"
        try:
            with psycopg.connect(self.dsn) as db:
                actor = self._authorize(db, capability)
                row = db.execute(
                    "SELECT current_version FROM reference_working.heads "
                    "WHERE space_id = %s AND reference_id = %s FOR UPDATE",
                    (self.space_id, reference.id),
                ).fetchone()
                actual = row[0] if row else None
                if actual != expected_version:
                    raise VersionConflictError("working reference version changed")
                previous = None
                if row:
                    record = db.execute(
                        "SELECT version, actor_id, recorded_at, reason, action, reference, validation, conversion "
                        "FROM reference_working.revisions "
                        "WHERE space_id = %s AND reference_id = %s AND version = %s",
                        (self.space_id, reference.id, actual),
                    ).fetchone()
                    if record is None:
                        raise ValueError("working head has no revision")
                    previous = self._decode(record)
                revision = prepare_revision(
                    reference,
                    previous_revision=previous,
                    actor_id=str(actor),
                    reason=reason,
                    action=action,
                    validation=validation,
                    conversion=conversion,
                )
                if previous is not None and revision.version == previous.version:
                    return revision.version
                if row is None:
                    db.execute(
                        "INSERT INTO reference_working.heads VALUES (%s, %s, %s)",
                        (self.space_id, reference.id, revision.version),
                    )
                db.execute(
                    "INSERT INTO reference_working.revisions "
                    "(space_id, reference_id, version, actor_id, recorded_at, reason, action, reference, validation, conversion) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        self.space_id,
                        reference.id,
                        revision.version,
                        actor,
                        revision.recorded_at,
                        reason,
                        action,
                        Jsonb(reference.model_dump(mode="json")),
                        Jsonb(validation.model_dump(mode="json")) if validation else None,
                        Jsonb(revision.conversion.model_dump(mode="json"))
                        if revision.conversion
                        else None,
                    ),
                )
                if row:
                    db.execute(
                        "UPDATE reference_working.heads SET current_version = %s "
                        "WHERE space_id = %s AND reference_id = %s",
                        (revision.version, self.space_id, reference.id),
                    )
                return revision.version
        except psycopg.errors.UniqueViolation as exc:
            raise VersionConflictError("working reference creation conflicted") from exc
