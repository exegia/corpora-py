"""Desktop discovery, socket ownership, and bounded parent-disconnect shutdown."""

import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

import pytest

from corpora_py import sidecar


@pytest.fixture
def fake_uvicorn(monkeypatch):
    import uvicorn

    config = Mock(wraps=uvicorn.Config)
    server = Mock(should_exit=False)
    constructor = Mock(return_value=server)
    monkeypatch.setattr(uvicorn, "Config", config)
    monkeypatch.setattr(uvicorn, "Server", constructor)
    return config, constructor, server


def test_loopback_discovery_preserves_bound_socket(fake_uvicorn, monkeypatch):
    config, constructor, server = fake_uvicorn
    monkeypatch.setenv("UVICORN_HOST", "0.0.0.0")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    before = dict(os.environ)
    stdout = Mock()
    monkeypatch.setattr(sidecar.sys, "stdout", stdout)
    sockets = []

    def run(*, sockets):
        (sock,) = sockets
        assert sock.family == socket.AF_INET
        assert sock.type == socket.SOCK_STREAM
        host, port = sock.getsockname()
        assert host == "127.0.0.1"
        assert 0 < port <= 65535
        assert stdout.write.call_args_list[0].args == (
            f'CORPORA_SIDECAR_LISTENING {{"url":"http://127.0.0.1:{port}"}}',
        )
        assert stdout.write.call_args_list[1].args == ("\n",)
        stdout.flush.assert_called_once_with()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as competing:
            with pytest.raises(OSError):
                competing.bind((host, port))
        held_config = constructor.call_args.args[0]
        assert held_config.app == "corpora_py.app:app"
        assert held_config.host == host
        assert held_config.port == port
        assert held_config.workers == 1
        assert held_config.reload is False
        assert held_config.access_log is False
        bound.append(sock)

    bound = sockets
    server.run.side_effect = run
    sidecar.run_sidecar()

    assert len(bound) == 1
    assert bound[0].fileno() == -1
    assert stdout.write.call_count == 2  # Exactly one newline-terminated record.
    config.assert_called_once()
    assert dict(os.environ) == before


@pytest.mark.parametrize("failure", ["config", "server", "announcement", "run"])
def test_socket_closed_on_failure(failure, fake_uvicorn, monkeypatch):
    config, constructor, server = fake_uvicorn
    real_socket = socket.socket
    sockets = []

    def create_socket(*args):
        sock = real_socket(*args)
        sockets.append(sock)
        return sock

    monkeypatch.setattr(sidecar.socket, "socket", create_socket)
    broken = Mock(side_effect=RuntimeError("launcher failure"))
    with monkeypatch.context() as patch:
        if failure == "config":
            config.side_effect = broken
        elif failure == "server":
            constructor.side_effect = broken
        elif failure == "announcement":
            patch.setattr(sidecar.sys, "stdout", Mock(write=broken))
        else:
            server.run.side_effect = broken
        with pytest.raises(RuntimeError, match="launcher failure"):
            sidecar.run_sidecar()
    assert len(sockets) == 1
    assert sockets[0].fileno() == -1


@pytest.mark.parametrize("watch_parent", [False, True])
def test_parent_watcher_is_opt_in_and_daemon(watch_parent, fake_uvicorn, monkeypatch):
    _, _, server = fake_uvicorn
    thread = Mock()
    constructor = Mock(return_value=thread)
    monkeypatch.setattr(sidecar.threading, "Thread", constructor)

    sidecar.run_sidecar(watch_parent=watch_parent)

    if watch_parent:
        constructor.assert_called_once_with(
            target=sidecar._watch_parent,
            args=(server, sys.stdin),
            name="corpora-sidecar-parent",
            daemon=True,
        )
        thread.start.assert_called_once_with()
    else:
        constructor.assert_not_called()
    server.run.assert_called_once()


@pytest.mark.parametrize("pipe_error", [None, OSError("lost pipe"), ValueError("closed pipe")])
def test_parent_disconnect_requests_exit_then_bounded_fallback(pipe_error, monkeypatch):
    server = Mock(should_exit=False)
    stdin = Mock()
    events = []

    def read(size):
        assert size == 1
        assert server.should_exit is False
        events.append("read")
        if len(events) == 1:
            return "x"  # Data is not a shutdown command.
        if pipe_error is not None:
            raise pipe_error
        return ""

    def sleep(seconds):
        assert server.should_exit is True
        assert seconds == 8.0
        events.append("grace")

    def force_exit(code):
        assert code == 0
        events.append("exit")

    stdin.read.side_effect = read
    monkeypatch.setattr(sidecar.time, "sleep", sleep)
    monkeypatch.setattr(sidecar.os, "_exit", force_exit)

    sidecar._watch_parent(server, stdin)

    assert server.should_exit is True
    assert events == ["read", "read", "grace", "exit"]


def test_eof_before_run_skips_server(fake_uvicorn, monkeypatch, capsys):
    _, _, server = fake_uvicorn
    monkeypatch.setattr(sidecar.sys, "stdin", io.StringIO())
    monkeypatch.setattr(sidecar.time, "sleep", Mock())
    force_exit = Mock()
    monkeypatch.setattr(sidecar.os, "_exit", force_exit)

    def thread(*, target, args, **kwargs):
        return Mock(start=lambda: target(*args))

    monkeypatch.setattr(sidecar.threading, "Thread", thread)
    sidecar.run_sidecar(watch_parent=True)

    assert server.should_exit is True
    server.run.assert_not_called()
    force_exit.assert_called_once_with(0)
    assert len(capsys.readouterr().out.splitlines()) == 1


@pytest.mark.parametrize("disconnect", ["before_serve", "during_startup"])
def test_uvicorn_preserves_exit_through_lifespan(disconnect, monkeypatch):
    """Exercise real Uvicorn so a future flag-reset regression is caught."""
    import uvicorn

    events = []
    monkeypatch.setattr(sidecar.time, "sleep", Mock())
    monkeypatch.setattr(sidecar.os, "_exit", Mock())

    async def app(scope, receive, send):
        assert scope["type"] == "lifespan"
        assert (await receive())["type"] == "lifespan.startup"
        events.append("startup")
        if disconnect == "during_startup":
            sidecar._watch_parent(server, io.StringIO())
        await send({"type": "lifespan.startup.complete"})
        assert (await receive())["type"] == "lifespan.shutdown"
        events.append("shutdown")
        await send({"type": "lifespan.shutdown.complete"})

    server = uvicorn.Server(uvicorn.Config(app, loop="asyncio", lifespan="on", log_config=None))
    if disconnect == "before_serve":
        sidecar._watch_parent(server, io.StringIO())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        server.run(sockets=[sock])
    assert server.should_exit is True
    assert events == ["startup", "shutdown"]


@pytest.mark.parametrize("argv,watch_parent", [([], False), (["--watch-parent"], True)])
def test_main(argv, watch_parent, monkeypatch):
    run = Mock()
    monkeypatch.setattr(sidecar, "run_sidecar", run)
    sidecar.main(argv)
    run.assert_called_once_with(watch_parent=watch_parent)


def test_import_and_help_do_not_import_uvicorn_or_app():
    code = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'uvicorn' or name.startswith('uvicorn.') or name == 'corpora_py.app':
        raise AssertionError('eager import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from corpora_py import sidecar
sidecar.main(['--help'])
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=10, check=True
    )
    assert "--watch-parent" in result.stdout
    assert "CORPORA_SIDECAR_LISTENING" not in result.stdout


def test_real_subprocess_health_auth_and_parent_eof(tmp_path):
    """Bounded smoke test of the combined app; never bypass authentication."""
    logs = tmp_path / "sidecar.log"
    env = {**os.environ, "AUTH_REQUIRED": "true"}
    with (
        logs.open("w") as stderr,
        subprocess.Popen(
            [sys.executable, "-u", "-m", "corpora_py.sidecar", "--watch-parent"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            env=env,
        ) as process,
    ):
        assert process.stdout is not None
        assert process.stdin is not None
        lines = queue.Queue()

        def read_stdout():
            for line in process.stdout:
                lines.put(line)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()
        try:
            record = lines.get(timeout=15)
            prefix = "CORPORA_SIDECAR_LISTENING "
            assert record.startswith(prefix)
            payload = json.loads(record.removeprefix(prefix))
            assert set(payload) == {"url"}
            url = payload["url"]
            assert url.startswith("http://127.0.0.1:")
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, logs.read_text()
                try:
                    with opener.open(url + "/health", timeout=0.5) as response:
                        assert json.load(response) == {"status": "ok"}
                    break
                except (URLError, TimeoutError, ConnectionError):
                    if time.monotonic() >= deadline:
                        pytest.fail("Sidecar health timed out: " + logs.read_text())
                    time.sleep(0.05)
            with opener.open(url + "/capabilities", timeout=2) as response:
                assert json.load(response)["auth_required"] is True
            with pytest.raises(HTTPError) as rejected:
                opener.open(url + "/convert/unknown-job", timeout=2)
            assert rejected.value.code == 401
            rejected.value.close()
            process.stdin.close()
            assert process.wait(timeout=12) == 0, logs.read_text()
            reader.join(timeout=2)
            assert not reader.is_alive()
            assert lines.empty()  # HTTP access logs must not pollute discovery stdout.
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
