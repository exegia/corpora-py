"""verify_jwt: fail-closed on missing config, AuthError wrapping, happy path."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from common.utils import jwt_auth
from common.utils.jwt_auth import AuthError, verify_jwt

JWKS_URL = "https://ref.supabase.co/auth/v1/.well-known/jwks.json"


@pytest.fixture(autouse=True)
def clear_jwks_cache():
    jwt_auth._jwks_client.cache_clear()
    yield
    jwt_auth._jwks_client.cache_clear()


def _fake_client(signing_key="public-key"):
    client = MagicMock()
    client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=signing_key)
    return client


class TestFailClosed:
    def test_none_jwks_url_raises(self):
        with pytest.raises(AuthError, match="No JWKS URL configured"):
            verify_jwt("token", jwks_url=None, audience="authenticated")

    def test_empty_jwks_url_raises(self):
        with pytest.raises(AuthError):
            verify_jwt("token", jwks_url="", audience="authenticated")


class TestVerification:
    def test_happy_path_returns_claims(self):
        claims = {"sub": "user-1", "aud": "authenticated"}
        with (
            patch.object(jwt_auth, "PyJWKClient", return_value=_fake_client()),
            patch.object(jwt_auth.jwt, "decode", return_value=claims) as decode,
        ):
            result = verify_jwt("tok", jwks_url=JWKS_URL, audience="authenticated")
        assert result == claims
        decode.assert_called_once_with(
            "tok", "public-key", algorithms=["RS256", "ES256"], audience="authenticated"
        )

    @pytest.mark.parametrize(
        "exc",
        [
            pyjwt.ExpiredSignatureError("expired"),
            pyjwt.InvalidSignatureError("bad sig"),
            pyjwt.InvalidAudienceError("wrong aud"),
            pyjwt.DecodeError("garbage"),
        ],
    )
    def test_pyjwt_errors_wrapped_as_autherror(self, exc):
        with (
            patch.object(jwt_auth, "PyJWKClient", return_value=_fake_client()),
            patch.object(jwt_auth.jwt, "decode", side_effect=exc),
            pytest.raises(AuthError, match="JWT verification failed"),
        ):
            verify_jwt("tok", jwks_url=JWKS_URL, audience="authenticated")

    def test_unknown_kid_wrapped_as_autherror(self):
        client = MagicMock()
        client.get_signing_key_from_jwt.side_effect = pyjwt.PyJWKClientError("kid not found")
        with (
            patch.object(jwt_auth, "PyJWKClient", return_value=client),
            pytest.raises(AuthError),
        ):
            verify_jwt("tok", jwks_url=JWKS_URL, audience="authenticated")


class TestClientCache:
    def test_client_cached_per_url(self):
        with patch.object(jwt_auth, "PyJWKClient", side_effect=lambda url: MagicMock()) as ctor:
            a1 = jwt_auth._jwks_client("https://a.test/jwks.json")
            a2 = jwt_auth._jwks_client("https://a.test/jwks.json")
            b = jwt_auth._jwks_client("https://b.test/jwks.json")
        assert a1 is a2
        assert a1 is not b
        assert ctor.call_count == 2
