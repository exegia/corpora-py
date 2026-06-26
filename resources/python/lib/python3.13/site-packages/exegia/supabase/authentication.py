"""Supabase authentication helpers.

Thin, typed wrappers around the shared synchronous Supabase client's auth
methods (``supabase.auth``). Each function builds the credential/options
payloads expected by ``supabase-auth`` and returns the library's own response
objects so callers keep full access to the resulting user and session.

All sign-in helpers raise ``supabase.AuthApiError`` (a subclass of
``supabase.AuthError``) when the auth server rejects the request.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from supabase_auth import AuthOtpResponse, AuthResponse, OAuthResponse, UserResponse

from exegia.supabase.client import supabase

logger = logging.getLogger(__name__)

# Providers that issue an OIDC ID token usable with ``sign_in_with_id_token``.
# The wider OIDC set also includes "azure", "facebook" and "kakao"; GitHub is
# intentionally excluded because it does not issue an OIDC id_token (use the
# OAuth flow via ``link_identity`` / ``sign_in_with_oauth`` for GitHub instead).
IdTokenProvider = Literal["apple", "google"]

# Provider identifiers accepted by the OAuth identity-linking flow.
OAuthProvider = Literal["apple", "google"]

# How widely a sign-out applies: this device, every device, or others only.
SignOutScope = Literal["global", "local", "others"]


def sign_in_with_id_token(
    provider: IdTokenProvider,
    token: str,
    *,
    access_token: str | None = None,
    nonce: str | None = None,
    captcha_token: str | None = None,
) -> AuthResponse:
    """Sign in (or sign up) using an OIDC ID token from Apple or Google.

    Use this for native sign-in flows where the client obtains an ID token
    directly from the provider (e.g. Sign in with Apple, Google Sign-In) and
    exchanges it for a Supabase session.

    Args:
        provider: The OIDC provider that issued the token ("apple" or "google").
        token: The OIDC ID token (JWT) returned by the provider.
        access_token: Optional provider access token, required by some
            providers to fetch additional profile details.
        nonce: Optional raw nonce that was used to obtain the ID token. Apple
            sign-in typically requires the nonce to be supplied here.
        captcha_token: Optional CAPTCHA verification token, when CAPTCHA
            protection is enabled on the project.

    Returns:
        The authenticated session and user.

    Raises:
        AuthApiError: If the token is invalid or the provider is misconfigured.
    """
    credentials: dict[str, Any] = {"provider": provider, "token": token}
    if access_token is not None:
        credentials["access_token"] = access_token
    if nonce is not None:
        credentials["nonce"] = nonce
    if captcha_token is not None:
        credentials["options"] = {"captcha_token": captcha_token}

    logger.info("Signing in with %s ID token", provider)
    return supabase.auth.sign_in_with_id_token(credentials)


def sign_in_with_otp_email(
    email: str,
    *,
    email_redirect_to: str | None = None,
    should_create_user: bool | None = None,
    data: dict[str, Any] | None = None,
    captcha_token: str | None = None,
) -> AuthOtpResponse:
    """Send a one-time passwordless login link / code to an email address.

    Triggers a magic-link or email OTP. No session is created here; the user
    completes sign-in by clicking the emailed link or by verifying the code
    via ``supabase.auth.verify_otp``.

    Args:
        email: The destination email address.
        email_redirect_to: Optional URL to redirect to after the user clicks
            the magic link.
        should_create_user: Whether to create a new user when the email is not
            already registered. Defaults to the project setting when omitted.
        data: Optional metadata stored on the user's ``user_metadata`` when a
            new user is created. Never use this for authorization decisions —
            it is user-editable.
        captcha_token: Optional CAPTCHA verification token, when CAPTCHA
            protection is enabled on the project.

    Returns:
        The OTP response, including ``message_id`` when available.

    Raises:
        AuthApiError: If the email cannot be dispatched.
    """
    options: dict[str, Any] = {}
    if email_redirect_to is not None:
        options["email_redirect_to"] = email_redirect_to
    if should_create_user is not None:
        options["should_create_user"] = should_create_user
    if data is not None:
        options["data"] = data
    if captcha_token is not None:
        options["captcha_token"] = captcha_token

    credentials: dict[str, Any] = {"email": email}
    if options:
        credentials["options"] = options

    logger.info("Sending email OTP")
    return supabase.auth.sign_in_with_otp(credentials)


def verify_otp_email(
    email: str,
    token: str,
    *,
    captcha_token: str | None = None,
) -> AuthResponse:
    """Verify an emailed OTP code and establish a session.

    This is the second step of the email passwordless flow started by
    :func:`sign_in_with_otp_email`: the code the user received is exchanged for
    an authenticated session.

    Args:
        email: The email address the OTP was sent to.
        token: The one-time code the user received by email.
        captcha_token: Optional CAPTCHA verification token, when CAPTCHA
            protection is enabled on the project.

    Returns:
        The authenticated session and user.

    Raises:
        AuthApiError: If the code is invalid or has expired.
    """
    params: dict[str, Any] = {"email": email, "token": token, "type": "email"}
    if captcha_token is not None:
        params["options"] = {"captcha_token": captcha_token}

    logger.info("Verifying email OTP")
    return supabase.auth.verify_otp(params)


def sign_in_anonymously(
    *,
    data: dict[str, Any] | None = None,
    captcha_token: str | None = None,
) -> AuthResponse:
    """Create and sign in a new anonymous user.

    Produces a real user record and session without any identity attached.
    The anonymous user can later be upgraded to a permanent one with
    :func:`link_identity` or :func:`update_user` (e.g. adding an email).

    Args:
        data: Optional metadata stored on the user's ``user_metadata``. Never
            use this for authorization decisions — it is user-editable.
        captcha_token: Optional CAPTCHA verification token, when CAPTCHA
            protection is enabled on the project.

    Returns:
        The session and the newly created anonymous user.

    Raises:
        AuthApiError: If anonymous sign-ins are disabled for the project.
    """
    options: dict[str, Any] = {}
    if data is not None:
        options["data"] = data
    if captcha_token is not None:
        options["captcha_token"] = captcha_token

    credentials: dict[str, Any] | None = {"options": options} if options else None

    logger.info("Creating anonymous user")
    return supabase.auth.sign_in_anonymously(credentials)


def link_identity(
    provider: OAuthProvider,
    *,
    redirect_to: str | None = None,
    scopes: str | None = None,
    query_params: dict[str, str] | None = None,
) -> OAuthResponse:
    """Link an additional OAuth identity to the currently signed-in user.

    Returns a provider authorization URL the user must visit to complete the
    link; it does not perform the redirect itself. Requires an active session.

    Args:
        provider: The OAuth provider to link ("apple" or "google").
        redirect_to: Optional URL to redirect to after authorization.
        scopes: Optional space-separated list of provider scopes to request.
        query_params: Optional extra query parameters for the authorization URL.

    Returns:
        The OAuth response containing the provider and authorization ``url``.

    Raises:
        AuthApiError: If there is no active session or linking is not allowed.
    """
    options: dict[str, Any] = {}
    if redirect_to is not None:
        options["redirect_to"] = redirect_to
    if scopes is not None:
        options["scopes"] = scopes
    if query_params is not None:
        options["query_params"] = query_params

    credentials: dict[str, Any] = {"provider": provider}
    if options:
        credentials["options"] = options

    logger.info("Linking %s identity to current user", provider)
    return supabase.auth.link_identity(credentials)


def update_user(
    *,
    email: str | None = None,
    phone: str | None = None,
    password: str | None = None,
    data: dict[str, Any] | None = None,
    nonce: str | None = None,
    current_password: str | None = None,
) -> UserResponse:
    """Update attributes of the currently signed-in user.

    Pass only the attributes to change. Changing ``email`` or ``phone`` may
    trigger a confirmation flow depending on project settings.

    Args:
        email: New email address.
        phone: New phone number.
        password: New password.
        data: Metadata to merge into the user's ``user_metadata``. Never use
            this for authorization decisions — it is user-editable.
        nonce: Verification nonce, required by some flows when updating a
            password without a recent re-authentication.
        current_password: The user's current password, when reauthentication
            is required to set a new one.

    Returns:
        The updated user.

    Raises:
        AuthApiError: If there is no active session or the update is rejected.
    """
    attributes: dict[str, Any] = {}
    if email is not None:
        attributes["email"] = email
    if phone is not None:
        attributes["phone"] = phone
    if password is not None:
        attributes["password"] = password
    if data is not None:
        attributes["data"] = data
    if nonce is not None:
        attributes["nonce"] = nonce
    if current_password is not None:
        attributes["current_password"] = current_password

    logger.info("Updating current user")
    return supabase.auth.update_user(attributes)


def get_current_user(jwt: str | None = None) -> UserResponse | None:
    """Return the currently signed-in user.

    Args:
        jwt: Optional access token to resolve a user for. When omitted, the
            client's stored session is used.

    Returns:
        The user response, or ``None`` when there is no active session.

    Raises:
        AuthApiError: If the supplied JWT is invalid.
    """
    return supabase.auth.get_user(jwt)


def sign_out(*, scope: SignOutScope | None = None) -> None:
    """Sign the current user out and revoke their session.

    Args:
        scope: Which sessions to revoke — "global" (all devices, the default),
            "local" (this session only), or "others" (every session except
            the current one).

    Raises:
        AuthApiError: If the session cannot be revoked.
    """
    options = {"scope": scope} if scope is not None else None

    logger.info("Signing out (scope=%s)", scope or "global")
    supabase.auth.sign_out(options)


def admin_sign_out(access_token: str, *, scope: SignOutScope | None = None) -> None:
    """Revoke a specific user's session server-side, by their access token.

    Unlike :func:`sign_out` (which acts on the client's own session), this uses
    the admin API and is the correct path for a service-role backend that holds
    no per-user session: it revokes the refresh token(s) for the user the JWT
    belongs to. Requires the client to be configured with the secret key.

    Args:
        access_token: The user's JWT whose session should be revoked.
        scope: Which sessions to revoke — "global" (all devices, the default),
            "local" (this session only), or "others" (every other session).

    Raises:
        AuthApiError: If the revoke request is rejected.
    """
    logger.info("Admin sign-out (scope=%s)", scope or "global")
    supabase.auth.admin.sign_out(access_token, scope or "global")
