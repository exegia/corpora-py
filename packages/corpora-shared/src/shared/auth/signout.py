"""Sign-out orchestration and the side-tasks that accompany a sign-out.

Signing a user out is two things: revoking their session server-side, and the
local bookkeeping that should happen alongside it (here, persisting the user's
last session activity to local storage so it survives the logout).

The shared client in :mod:`shared.supabase.client` uses the service-role key
and carries no per-user session, so a plain ``auth.sign_out()`` would be a
silent no-op (it revokes only the client's own — absent — session). This module
therefore takes the user's ``access_token`` and revokes via the admin API
(:func:`shared.supabase.authentication.admin_sign_out`).

The revoke is the critical step; recording activity is best-effort and never
fails the sign-out. The two run sequentially so the saved record can capture
whether the revoke actually succeeded. Activity is stored one file per user
(``.state/session_activity/<user_id>.json``) to avoid read-modify-write races
when several users sign out concurrently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.supabase import authentication
from shared.supabase.authentication import SignOutScope
from shared.utils.constant import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Local storage for per-user "last session activity" records.
DEFAULT_ACTIVITY_DIR = PROJECT_ROOT / ".state" / "session_activity"


@dataclass(frozen=True)
class SignOutResult:
    """Outcome of a sign-out attempt.

    Attributes:
        ok: Whether the server-side session revoke succeeded.
        scope: The scope the revoke was requested with.
        revoked: Whether the user's session was revoked server-side.
        activity_saved: Whether the local activity record was written.
        activity_path: Path to the written activity file, when saved.
        message: A user-facing message, set when the sign-out did not succeed.
    """

    ok: bool
    scope: SignOutScope
    revoked: bool
    activity_saved: bool
    activity_path: Path | None = None
    message: str | None = None


def record_session_activity(
    user_id: str,
    *,
    scope: SignOutScope,
    revoke_ok: bool,
    activity_dir: Path = DEFAULT_ACTIVITY_DIR,
    signed_out_at: datetime | None = None,
) -> Path:
    """Persist a user's last session activity to a per-user local JSON file.

    Args:
        user_id: The auth user id the activity belongs to (also the file name).
        scope: The sign-out scope that was applied.
        revoke_ok: Whether the server-side revoke succeeded.
        activity_dir: Directory holding the per-user activity files.
        signed_out_at: Timestamp to record; defaults to now (UTC).

    Returns:
        The path of the written activity file.

    Raises:
        OSError: If the file cannot be written.
    """
    timestamp = (signed_out_at or datetime.now(timezone.utc)).isoformat()
    record: dict[str, Any] = {
        "user_id": user_id,
        "signed_out_at": timestamp,
        "scope": scope,
        "revoke_ok": revoke_ok,
    }

    activity_dir.mkdir(parents=True, exist_ok=True)
    path = activity_dir / f"{user_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True))
    return path


def get_last_session_activity(
    user_id: str,
    *,
    activity_dir: Path = DEFAULT_ACTIVITY_DIR,
) -> dict[str, Any] | None:
    """Return the last recorded sign-out activity for a user, or ``None``.

    Args:
        user_id: The auth user id to look up.
        activity_dir: Directory holding the per-user activity files.

    Returns:
        The stored activity record, or ``None`` if none exists or it is
        unreadable.
    """
    path = activity_dir / f"{user_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read session activity at %s", path)
        return None


def sign_out(
    access_token: str,
    user_id: str,
    *,
    scope: SignOutScope | None = None,
    save_activity: bool = True,
    activity_dir: Path | None = None,
) -> SignOutResult:
    """Sign a user out: revoke their session, then record last activity locally.

    The revoke is performed via the admin API (the service-role client has no
    session of its own to sign out). Recording activity is best-effort: a
    storage error is logged but never fails the sign-out.

    Args:
        access_token: The user's JWT, used to revoke their session.
        user_id: The user's auth id, used to key the local activity record.
        scope: Which sessions to revoke — "global" (default), "local", or
            "others".
        save_activity: Whether to persist last session activity locally.
        activity_dir: Override for the activity storage directory.

    Returns:
        A :class:`SignOutResult` describing what happened.
    """
    effective_scope: SignOutScope = scope or "global"
    target_dir = activity_dir or DEFAULT_ACTIVITY_DIR

    # 1. Revoke the user's session server-side — the critical step.
    revoked = False
    revoke_error: Exception | None = None
    try:
        authentication.admin_sign_out(access_token, scope=scope)
        revoked = True
    except Exception as exc:  # best-effort: surface via result, never crash
        revoke_error = exc
        logger.error("Failed to revoke session for %s: %s", user_id, exc)

    # 2. Record last session activity locally — best-effort, captures outcome.
    activity_path: Path | None = None
    if save_activity:
        try:
            activity_path = record_session_activity(
                user_id,
                scope=effective_scope,
                revoke_ok=revoked,
                activity_dir=target_dir,
            )
        except OSError as exc:
            logger.warning(
                "Failed to persist session activity for %s: %s", user_id, exc
            )

    if revoke_error is not None:
        return SignOutResult(
            ok=False,
            scope=effective_scope,
            revoked=False,
            activity_saved=activity_path is not None,
            activity_path=activity_path,
            message="Sign-out failed; the session may still be active.",
        )

    logger.info("Signed out user %s (scope=%s)", user_id, effective_scope)
    return SignOutResult(
        ok=True,
        scope=effective_scope,
        revoked=True,
        activity_saved=activity_path is not None,
        activity_path=activity_path,
    )
