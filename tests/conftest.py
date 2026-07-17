"""Shared fixtures for the whole suite.

Several modules build singletons at import time (`common.utils.config.settings`,
`corpora_mcp.corpus.corpus_manager`, `corpora_mcp.server._cursors`). Tests never
mutate those directly; they either build fresh instances or reset state via the
autouse fixtures defined in the package-level conftests.
"""

import pytest
from common.utils.config import Settings


@pytest.fixture
def make_settings(monkeypatch):
    """Build a fresh Settings from explicit env vars, ignoring any .env file."""

    def _make(**env: str) -> Settings:
        for var in (
            "ENVIRONMENT",
            "CORS_ORIGINS",
            "OPENAI_KEY",
            "AUTH_REQUIRED",
            "PROJECT_REF",
            "SUPABASE_JWKS_URL",
            "HF_TOKEN",
            "HF_STORAGE_REPO",
        ):
            monkeypatch.delenv(var, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)

    return _make
