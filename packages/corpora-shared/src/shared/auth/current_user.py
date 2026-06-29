"""User-related functions for authentication and authorization.

Resolves the *current user* from an access token and joins it with the
application's own ``public.users`` record, exposing convenient conditionals for
the auth state (anonymous vs. permanent, linked providers, profile presence).

The shared client in :mod:`shared.supabase.client` is built with the
service-role key, so it carries no per-request user session. Every function
here therefore takes the caller's ``access_token`` (the user's JWT) explicitly
rather than relying on a stored session:

* ``auth.get_user(token)`` resolves the user from that token.
* The ``public.users`` lookup runs under the service role and bypasses RLS, so
  it returns the row regardless of session state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from supabase_auth import User  # pyright: ignore[reportMissingImports]

from shared.supabase.authentication import (
    OAuthProvider,
    get_current_user,
    link_identity,
)
from shared.supabase.client import supabase

logger = logging.getLogger(__name__)

# Application user table mirroring ``auth.users`` (one row per auth user).
USERS_TABLE = "users"
# Column on ``public.users`` that equals ``auth.users.id``.
USERS_ID_COLUMN = "id"


@dataclass(frozen=True)
class CurrentUser:
    """The current user: the Supabase auth identity plus its ``public.users`` row.

    Attributes:
        auth_user: The authenticated user from Supabase Auth (``auth.users``).
        profile: The matching ``public.users`` record, or ``None`` when no
            application row exists yet (e.g. a freshly created anonymous user).
    """

    auth_user: User
    profile: dict[str, Any] | None

    @property
    def id(self) -> str:
        """The auth user's UUID (also the ``public.users`` primary key)."""
        return self.auth_user.id

    @property
    def email(self) -> str | None:
        """The user's email, if one is attached to the auth identity."""
        return self.auth_user.email

    @property
    def is_anonymous(self) -> bool:
        """Whether this is an anonymous (not-yet-linked) user."""
        return bool(self.auth_user.is_anonymous)

    @property
    def is_permanent(self) -> bool:
        """Whether the user has been upgraded past the anonymous stage.

        Note: anonymous users still carry the ``authenticated`` role, so this is
        the meaningful "is this a real, claimable account" check — not role.
        """
        return not self.is_anonymous

    @property
    def has_profile(self) -> bool:
        """Whether a ``public.users`` record was found for this user."""
        return self.profile is not None

    @property
    def providers(self) -> list[str]:
        """The identity providers linked to this user (e.g. ``["google"]``)."""
        identities = self.auth_user.identities or []
        return [identity.provider for identity in identities]

    def has_provider(self, provider: str) -> bool:
        """Return whether ``provider`` is already linked to this user."""
        return provider in self.providers


def get_profile(user_id: str) -> dict[str, Any] | None:
    """Fetch the ``public.users`` record for a given auth user id.

    Args:
        user_id: The auth user UUID (``auth.users.id``).

    Returns:
        The full ``public.users`` row as a dict, or ``None`` when no matching
        record exists.
    """
    response = (
        supabase.table(USERS_TABLE)
        .select("*")
        .eq(USERS_ID_COLUMN, user_id)
        .maybe_single()
        .execute()
    )
    return response.data if response else None


def get_current_user_record(access_token: str) -> CurrentUser | None:
    """Resolve the current user from an access token and join its profile.

    Args:
        access_token: The user's JWT (e.g. from the ``Authorization`` header).

    Returns:
        A :class:`CurrentUser` combining the auth identity and the
        ``public.users`` row, or ``None`` when the token maps to no user.

    Raises:
        AuthApiError: If the access token is invalid or expired.
    """
    response = get_current_user(access_token)
    if response is None or response.user is None:
        return None

    auth_user = response.user
    profile = get_profile(auth_user.id)
    return CurrentUser(auth_user=auth_user, profile=profile)


def link_identity_to_current_user(
    access_token: str,
    provider: OAuthProvider,
    *,
    redirect_to: str | None = None,
    scopes: str | None = None,
    query_params: dict[str, str] | None = None,
):
    """Link an OAuth identity to the current user.

    The motivating case is upgrading an anonymous user by linking an Apple or
    Google identity, but linking an additional provider to an already-permanent
    user is also valid and allowed here.

    Returns a provider authorization URL the user must visit to complete the
    link; it does not perform the redirect itself (when running server-side,
    the caller handles the returned ``url``).

    Per the supabase-py reference, ``auth.link_identity`` requires that:
    "Enable Manual Linking" is turned on in the project's auth settings, the
    user is signed in (the client must carry that user's session — e.g. set
    via ``auth.set_session`` when using the service-role client), and the
    candidate identity is not already linked to this or another user.

    Args:
        access_token: The current user's JWT, used to confirm the user exists
            and to detect whether this is an anonymous-account upgrade.
        provider: The OAuth provider to link ("apple" or "google").
        redirect_to: Optional URL to redirect to after authorization.
        scopes: Optional space-separated list of provider scopes to request.
        query_params: Optional extra query parameters for the authorization URL.

    Returns:
        The OAuth response containing the provider and authorization ``url``.

    Raises:
        ValueError: If the access token maps to no current user.
        AuthApiError: If linking is rejected by the auth server.
    """
    current = get_current_user_record(access_token)
    if current is None:
        raise ValueError("No current user for the provided access token.")

    if current.is_anonymous:
        logger.info("Upgrading anonymous user %s by linking %s", current.id, provider)
    elif current.has_provider(provider):
        logger.warning("User %s already has a linked %s identity", current.id, provider)
    else:
        logger.info("Linking additional %s identity to user %s", provider, current.id)

    return link_identity(
        provider,
        redirect_to=redirect_to,
        scopes=scopes,
        query_params=query_params,
    )
