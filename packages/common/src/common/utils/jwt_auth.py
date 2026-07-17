"""Framework-agnostic Supabase JWT verification (JWKS-based).

Deliberately has no FastAPI/Starlette import -- `corpora_py.auth` is where
this gets turned into request-handling policy (which paths are gated, what
happens on failure). This module only answers one question: is this token a
genuine, unexpired Supabase access token?

Supabase (hosted, current-generation projects) signs JWTs asymmetrically
(RS256/ES256) and publishes verification keys at a JWKS endpoint
(`<project>.supabase.co/auth/v1/.well-known/jwks.json`), rather than a shared
HS256 secret. Verifying against JWKS means fetching (and caching) that
project's public keys -- the one network dependency this otherwise-offline
sidecar has, and only when auth is actually enforced and a token needs
checking.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient


class AuthError(Exception):
    """JWT failed verification (missing config, bad signature, expired, ...).

    Callers (e.g. `corpora_py.auth`) are expected to catch this and respond
    with a generic 401 -- the exception message is for server-side logs, not
    for round-tripping to the client (same rationale as
    `admin.services.jobs.JobManager._run`'s error handling).
    """


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    # Cached per URL (there's realistically only ever one) so repeated
    # verifications reuse `PyJWKClient`'s internal signing-key cache instead
    # of refetching the JWKS document on every request.
    return PyJWKClient(jwks_url)


def verify_jwt(token: str, *, jwks_url: str | None, audience: str) -> dict[str, Any]:
    """Verify `token` against `jwks_url` and return its decoded claims.

    Raises `AuthError` if `jwks_url` is unset, the token's `kid` isn't found
    in the JWKS, the signature is invalid, or the token is expired/not-yet-valid.
    """
    if not jwks_url:
        raise AuthError(
            "No JWKS URL configured (set PROJECT_REF or SUPABASE_JWKS_URL) -- "
            "cannot verify tokens with AUTH_REQUIRED enabled"
        )
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=audience,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"JWT verification failed: {exc}") from exc
