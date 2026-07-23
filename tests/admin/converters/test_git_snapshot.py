"""`_git_snapshot` degrades gracefully when no `git` binary is on PATH.

Serverless Python runtimes (Vercel Functions) ship no git, and the
unguarded `subprocess.run("git", ...)` there raised `FileNotFoundError`
*after* the whole parse -> TF -> .cfm pipeline had already succeeded,
failing every conversion at the final packaging step.

These tests have to fake git's absence: CI and dev machines both have git
installed, so the skip branch never fires on its own.
"""

import importlib
import subprocess

import pytest

# `admin.converters.__init__` re-exports the *function* `convert_to_corpus`,
# which shadows the submodule of the same name -- any `import
# admin.converters.convert_to_corpus as mod` form binds the function, not the
# module. `import_module` reaches the module itself.
mod = importlib.import_module("admin.converters.convert_to_corpus")


class TestGitSnapshot:
    def test_skips_when_git_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod.shutil, "which", lambda _: None)

        def fail(*args, **kwargs):  # pragma: no cover - must never be reached
            raise AssertionError("shelled out to git despite it being absent")

        monkeypatch.setattr(mod.subprocess, "run", fail)

        (tmp_path / "manifest.yml").write_text("uid: x\n")
        mod._git_snapshot(tmp_path)  # must not raise

        assert not (tmp_path / ".git").exists()

    def test_commits_when_git_available(self, tmp_path):
        if mod.shutil.which("git") is None:
            pytest.skip("git not installed in this environment")

        (tmp_path / "manifest.yml").write_text("uid: x\n")
        mod._git_snapshot(tmp_path)

        assert (tmp_path / ".git").is_dir()
        log = subprocess.run(
            ("git", "log", "--oneline"),
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Initial corpus payload" in log.stdout

    def test_real_git_failure_still_raises(self, tmp_path, monkeypatch):
        """The guard is `shutil.which`, not a blanket `except
        FileNotFoundError` -- a genuine git failure must still surface."""
        monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/git")
        monkeypatch.setattr(
            mod.subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, "git")
            ),
        )

        with pytest.raises(subprocess.CalledProcessError):
            mod._git_snapshot(tmp_path)
