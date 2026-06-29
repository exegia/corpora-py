"""Sign-in orchestration: expose the sign-in flows and the surrounding legwork.

This module wraps the low-level auth methods in
:mod:`shared.supabase.authentication` and adds the application-level step that
matters on login: once a provider authenticates the user, confirm that a
matching ``public.users`` record exists. If it does, the caller receives a
:class:`~shared.auth.current_user.CurrentUser` payload (the ``auth.users``
identity joined with its ``public.users`` row). If it does not, the caller
receives a friendly result inviting the user to sign up instead.

``public.users`` is assumed to be keyed by ``auth.users.id``, so the lookup for
"the provider id used" resolves to the id of the user that just authenticated.

Flows that yield a session immediately (ID token) resolve in one call. The
email OTP flow is two steps — :func:`request_email_otp` only sends the code (no
session yet), and :func:`verify_email_otp` completes the login — so the profile
check runs at verification time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from supabase_auth import AuthOtpResponse, AuthResponse, Session

from shared.auth.current_user import CurrentUser, get_profile
from shared.supabase import authentication
from shared.supabase.authentication import IdTokenProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignInResult:
    """Outcome of a sign-in attempt.

    Attributes:
        ok: Whether the user is fully signed in (authenticated *and* has a
            ``public.users`` record).
        current_user: The combined auth + profile payload, set only when ``ok``.
        session: The Supabase session (access/refresh tokens), set whenever the
            provider authenticated the user — including the ``needs_signup``
            case, so the caller can complete registration.
        message: A user-facing message, set on the non-``ok`` paths.
        needs_signup: True when the user authenticated but has no
            ``public.users`` record yet, i.e. they should be offered sign-up.
    """

    ok: bool
    current_user: CurrentUser | None = None
    session: Session | None = None
    message: str | None = None
    needs_signup: bool = False


def _resolve_login(response: AuthResponse, provider_label: str) -> SignInResult:
    """Run the post-authentication legwork and build a :class:`SignInResult`.

    Looks up the ``public.users`` record for the just-authenticated user and
    decides between a successful login and a "needs sign-up" outcome.

    Args:
        response: The auth response returned by a session-producing sign-in.
        provider_label: Human-readable label for the method used (e.g.
            "Google", "Apple", "email"), used in the sign-up message.
    """
    user = response.user
    if user is None:
        logger.warning("Sign-in via %s returned no user", provider_label)
        return SignInResult(
            ok=False,
            message="We couldn't sign you in. Please try again.",
        )

    profile = get_profile(user.id)
    if profile is None:
        logger.info("No public.users record for %s; offering sign-up", user.id)
        return SignInResult(
            ok=False,
            session=response.session,
            needs_signup=True,
            message=(
                f"No account is linked to your {provider_label} sign-in yet. "
                "Would you like to create one?"
            ),
        )

    logger.info("Sign-in complete for user %s via %s", user.id, provider_label)
    return SignInResult(
        ok=True,
        current_user=CurrentUser(auth_user=user, profile=profile),
        session=response.session,
    )


def sign_in_with_id_token(
    provider: IdTokenProvider,
    token: str,
    *,
    access_token: str | None = None,
    nonce: str | None = None,
    captcha_token: str | None = None,
) -> SignInResult:
    """Sign in with an Apple or Google OIDC ID token, then verify the profile.

    Args:
        provider: The OIDC provider that issued the token ("apple" or "google").
        token: The OIDC ID token (JWT) returned by the provider.
        access_token: Optional provider access token.
        nonce: Optional raw nonce used to obtain the ID token (Apple typically
            requires this).
        captcha_token: Optional CAPTCHA verification token.

    Returns:
        A :class:`SignInResult`: a full payload on success, or a sign-up
        invitation when the authenticated user has no ``public.users`` record.

    Raises:
        AuthApiError: If the ID token is invalid or the provider is
            misconfigured.
    """
    response = authentication.sign_in_with_id_token(
        provider,
        token,
        access_token=access_token,
        nonce=nonce,
        captcha_token=captcha_token,
    )
    return _resolve_login(response, provider.capitalize())


def request_email_otp(
    email: str,
    *,
    email_redirect_to: str | None = None,
    should_create_user: bool | None = None,
    captcha_token: str | None = None,
) -> AuthOtpResponse:
    """Send a one-time login code / magic link to an email address.

    This is the first step of the email sign-in flow and does not create a
    session; complete the login with :func:`verify_email_otp`. No profile check
    happens here because the user is not authenticated yet.

    Args:
        email: The destination email address.
        email_redirect_to: Optional URL to redirect to after a magic-link click.
        should_create_user: Whether to create a new auth user when the email is
            unknown. Defaults to the project setting when omitted.
        captcha_token: Optional CAPTCHA verification token.

    Returns:
        The OTP dispatch response (includes ``message_id`` when available).

    Raises:
        AuthApiError: If the code cannot be dispatched.
    """
    return authentication.sign_in_with_otp_email(
        email,
        email_redirect_to=email_redirect_to,
        should_create_user=should_create_user,
        captcha_token=captcha_token,
    )


def verify_email_otp(
    email: str,
    token: str,
    *,
    captcha_token: str | None = None,
) -> SignInResult:
    """Complete email sign-in by verifying the OTP, then verify the profile.

    Args:
        email: The email address the code was sent to.
        token: The one-time code the user received.
        captcha_token: Optional CAPTCHA verification token.

    Returns:
        A :class:`SignInResult`: a full payload on success, or a sign-up
        invitation when the authenticated user has no ``public.users`` record.

    Raises:
        AuthApiError: If the code is invalid or has expired.
    """
    response = authentication.verify_otp_email(
        email, token, captcha_token=captcha_token
    )
    return _resolve_login(response, "email")
