"""AuthMiddleware: exempt paths, bearer/query token extraction, rejects, claims."""

import pytest

from common.utils.jwt_auth import AuthError
from corpora_py import auth as auth_module
from corpora_py.auth import AuthMiddleware, _extract_bearer_token


class DownstreamApp:
    def __init__(self):
        self.called = False
        self.scope = None

    async def __call__(self, scope, receive, send):
        self.called = True
        self.scope = scope


def _scope(scope_type="http", path="/convert", headers=None, query=b""):
    return {
        "type": scope_type,
        "path": path,
        "headers": headers or [],
        "query_string": query,
    }


class SendRecorder:
    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)


@pytest.fixture
def downstream():
    return DownstreamApp()


@pytest.fixture
def middleware(downstream):
    return AuthMiddleware(downstream)


@pytest.fixture(autouse=True)
def auth_enabled(monkeypatch):
    monkeypatch.setattr(auth_module.settings, "auth_required", True)


@pytest.fixture
def accept_all(monkeypatch):
    claims = {"sub": "user-1", "aud": "authenticated"}
    monkeypatch.setattr(auth_module, "verify_jwt", lambda *a, **k: claims)
    return claims


@pytest.fixture
def reject_all(monkeypatch):
    def _raise(*args, **kwargs):
        raise AuthError("bad token")

    monkeypatch.setattr(auth_module, "verify_jwt", _raise)


class TestExtractBearerToken:
    def test_standard_header(self):
        headers = [(b"authorization", b"Bearer abc123")]
        assert _extract_bearer_token(headers) == "abc123"

    def test_case_insensitive_scheme_and_header(self):
        headers = [(b"Authorization", b"bearer XYZ")]
        # header key comparison is lowercase; ASGI lowercases keys in practice
        assert _extract_bearer_token([(k.lower(), v) for k, v in headers]) == "XYZ"

    def test_whitespace_stripped(self):
        assert _extract_bearer_token([(b"authorization", b"Bearer  tok  ")]) == "tok"

    def test_non_bearer_scheme_ignored(self):
        assert _extract_bearer_token([(b"authorization", b"Basic dXNlcg==")]) is None

    def test_missing_header(self):
        assert _extract_bearer_token([(b"accept", b"*/*")]) is None


class TestExemptAndBypass:
    @pytest.mark.parametrize(
        "path", ["/health", "/", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"]
    )
    async def test_exempt_paths_pass_without_token(self, middleware, downstream, path):
        await middleware(_scope(path=path), None, SendRecorder())
        assert downstream.called

    async def test_auth_disabled_passes_everything(
        self, middleware, downstream, monkeypatch
    ):
        monkeypatch.setattr(auth_module.settings, "auth_required", False)
        await middleware(_scope(path="/convert"), None, SendRecorder())
        assert downstream.called

    async def test_lifespan_scope_passes_through(self, middleware, downstream):
        await middleware({"type": "lifespan"}, None, SendRecorder())
        assert downstream.called


class TestHttpRejection:
    async def test_missing_token_401(self, middleware, downstream):
        send = SendRecorder()
        await middleware(_scope(path="/convert"), None, send)
        assert not downstream.called
        start = next(m for m in send.messages if m["type"] == "http.response.start")
        assert start["status"] == 401

    async def test_invalid_token_401(self, middleware, downstream, reject_all):
        send = SendRecorder()
        scope = _scope(headers=[(b"authorization", b"Bearer bad")])
        await middleware(scope, None, send)
        assert not downstream.called
        start = next(m for m in send.messages if m["type"] == "http.response.start")
        assert start["status"] == 401

    async def test_query_token_not_accepted_for_http(self, middleware, downstream, accept_all):
        send = SendRecorder()
        await middleware(_scope(query=b"token=abc"), None, send)
        assert not downstream.called  # ?token= is a WebSocket-only fallback


class TestWebSocketRejection:
    async def test_missing_token_closes_4401_before_accept(self, middleware, downstream):
        send = SendRecorder()
        await middleware(_scope("websocket", path="/convert/x/ws"), None, send)
        assert not downstream.called
        assert send.messages == [{"type": "websocket.close", "code": 4401}]

    async def test_invalid_token_closes_4401(self, middleware, downstream, reject_all):
        send = SendRecorder()
        scope = _scope("websocket", query=b"token=bad")
        await middleware(scope, None, send)
        assert send.messages == [{"type": "websocket.close", "code": 4401}]


class TestSuccess:
    async def test_http_bearer_token_stashes_claims(
        self, middleware, downstream, accept_all
    ):
        scope = _scope(headers=[(b"authorization", b"Bearer good")])
        await middleware(scope, None, SendRecorder())
        assert downstream.called
        assert downstream.scope["state"]["user"] == accept_all

    async def test_websocket_query_token_accepted(
        self, middleware, downstream, accept_all
    ):
        scope = _scope("websocket", path="/convert/x/ws", query=b"token=good")
        await middleware(scope, None, SendRecorder())
        assert downstream.called
        assert downstream.scope["state"]["user"] == accept_all

    async def test_websocket_header_token_preferred(self, middleware, downstream, monkeypatch):
        seen = {}

        def spy(token, **kwargs):
            seen["token"] = token
            return {"sub": "u"}

        monkeypatch.setattr(auth_module, "verify_jwt", spy)
        scope = _scope(
            "websocket",
            headers=[(b"authorization", b"Bearer header-tok")],
            query=b"token=query-tok",
        )
        await middleware(scope, None, SendRecorder())
        assert seen["token"] == "header-tok"

    async def test_existing_state_preserved(self, middleware, downstream, accept_all):
        scope = _scope(headers=[(b"authorization", b"Bearer good")])
        scope["state"] = {"other": "value"}
        await middleware(scope, None, SendRecorder())
        assert downstream.scope["state"] == {"other": "value", "user": accept_all}
