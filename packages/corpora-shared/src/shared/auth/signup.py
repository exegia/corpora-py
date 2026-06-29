"""Sign-up orchestration: complete registration and provision the profile row.

In this app, "authentication" and "sign-up" are separate steps. A user first
authenticates with a provider (Apple/Google ID token, email OTP) or as an
anonymous guest — that creates the ``auth.users`` identity. Sign-up is what
happens next: creating the matching ``public.users`` record, keyed by
``auth.users.id``, so the application has a profile to hang data off.

This module offers two entry points:

* :func:`sign_up` — for an already-authenticated user (pass their access token),
  or, via the ``anonymous`` option, begin a fresh anonymous session first and
  register that guest.
* :func:`start_anonymous_session` — the standalone anonymous-login helper,
  delegating to :func:`shared.supabase.authentication.sign_in_anonymously`.

``public.users`` is assumed to have ``id uuid references auth.users(id)``;
inserting ``id = auth_user.id`` establishes that relationship. The service-role
client is used for the insert, which bypasses RLS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from supabase_auth import AuthResponse, Session

from shared.auth.current_user import (
    USERS_ID_COLUMN,
    USERS_TABLE,
    CurrentUser,
    get_profile,
)
from shared.supabase import authentication
from shared.supabase.client import supabase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignUpResult:
    """Outcome of a sign-up attempt.

    Attributes:
        ok: Whether a new ``public.users`` record was created for the user.
        current_user: The combined auth + profile payload. Set on success, and
            also on the ``already_registered`` path (the existing record).
        session: The session, when sign-up started one (anonymous flow).
        message: A user-facing message, set on the non-``ok`` paths.
        already_registered: True when the user already had a profile, so no new
            record was created.
    """

    ok: bool
    current_user: CurrentUser | None = None
    session: Session | None = None
    message: str | None = None
    already_registered: bool = False


def create_user_profile(
    user_id: str,
    *,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a ``public.users`` record for an auth user.

    Args:
        user_id: The ``auth.users.id`` to key the record by (the FK relationship).
        fields: Optional additional columns to set on the row, matching your
            ``public.users`` schema (e.g. ``display_name``).

    Returns:
        The created row.

    Raises:
        APIError: If the insert fails (e.g. a record already exists).
    """
    row: dict[str, Any] = {USERS_ID_COLUMN: user_id, **(fields or {})}
    response = supabase.table(USERS_TABLE).insert(row).execute()
    return response.data[0] if response.data else row


def start_anonymous_session(
    *,
    data: dict[str, Any] | None = None,
    captcha_token: str | None = None,
) -> AuthResponse:
    """Start a session via anonymous login (no profile created here).

    Thin delegate to :func:`shared.supabase.authentication.sign_in_anonymously`,
    exposed so callers can begin a guest session independently of sign-up.

    Args:
        data: Optional metadata stored on the anonymous user's ``user_metadata``.
        captcha_token: Optional CAPTCHA verification token.

    Returns:
        The auth response with the new anonymous user and session.

    Raises:
        AuthApiError: If anonymous sign-ins are disabled for the project.
    """
    return authentication.sign_in_anonymously(data=data, captcha_token=captcha_token)


def sign_up(
    *,
    access_token: str | None = None,
    profile_fields: dict[str, Any] | None = None,
    anonymous: bool = False,
    anonymous_metadata: dict[str, Any] | None = None,
    captcha_token: str | None = None,
) -> SignUpResult:
    """Complete sign-up by creating the user's ``public.users`` record.

    Provide ``access_token`` for a user who already authenticated (Apple/Google
    ID token, email OTP), or set ``anonymous=True`` to begin a fresh anonymous
    session and register that guest. Exactly one of those is required.

    If the user already has a ``public.users`` record, no new record is created
    and the result reports ``already_registered``.

    Args:
        access_token: JWT of an already-authenticated user to register.
        profile_fields: Optional extra columns for the ``public.users`` row.
        anonymous: When True, start an anonymous session (via the authentication
            module) and register that user instead of using ``access_token``.
        anonymous_metadata: Optional ``user_metadata`` for the anonymous user,
            used only when ``anonymous`` is True.
        captcha_token: Optional CAPTCHA token for the anonymous sign-in.

    Returns:
        A :class:`SignUpResult`.

    Raises:
        AuthApiError: If anonymous sign-in fails or the access token is invalid.
        APIError: If the profile insert fails unexpectedly.
    """
    session: Session | None = None

    if anonymous:
        response = start_anonymous_session(
            data=anonymous_metadata, captcha_token=captcha_token
        )
        user = response.user
        session = response.session
    elif access_token:
        user_response = authentication.get_current_user(access_token)
        user = user_response.user if user_response else None
    else:
        return SignUpResult(
            ok=False,
            message="Provide an access token or enable an anonymous session to sign up.",
        )

    if user is None:
        logger.warning("Sign-up could not resolve a user to register")
        return SignUpResult(
            ok=False,
            session=session,
            message="We couldn't complete sign-up. Please try again.",
        )

    existing = get_profile(user.id)
    if existing is not None:
        logger.info("User %s already has a profile; skipping creation", user.id)
        return SignUpResult(
            ok=False,
            current_user=CurrentUser(auth_user=user, profile=existing),
            session=session,
            already_registered=True,
            message="You already have an account. Please sign in instead.",
        )

    profile = create_user_profile(user.id, fields=profile_fields)
    logger.info("Created public.users record for %s", user.id)
    return SignUpResult(
        ok=True,
        current_user=CurrentUser(auth_user=user, profile=profile),
        session=session,
    )
