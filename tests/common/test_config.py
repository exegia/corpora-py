"""Settings: env binding, jwks_url resolution, cors parsing, auth default."""

import pytest
from common.utils.config import Settings
from pydantic import ValidationError


def _settings(**kwargs) -> Settings:
    """Fresh Settings from explicit constructor args, no .env file."""
    return Settings(_env_file=None, **kwargs)


class TestAuthDefaults:
    def test_auth_required_defaults_true(self):
        assert _settings().auth_required is True

    def test_auth_required_env_opt_out(self, make_settings):
        assert make_settings(AUTH_REQUIRED="false").auth_required is False

    def test_default_audience(self):
        assert _settings().supabase_jwt_audience == "authenticated"


class TestJwksUrl:
    def test_explicit_url_wins(self):
        s = _settings(
            supabase_jwks_url="http://localhost:54321/auth/v1/.well-known/jwks.json",
            project_ref="abc123",
        )
        assert s.jwks_url == "http://localhost:54321/auth/v1/.well-known/jwks.json"

    def test_derived_from_project_ref(self):
        s = _settings(project_ref="abc123", supabase_jwks_url=None)
        assert s.jwks_url == "https://abc123.supabase.co/auth/v1/.well-known/jwks.json"

    def test_none_when_unconfigured(self):
        s = _settings(project_ref=None, supabase_jwks_url=None)
        assert s.jwks_url is None

    def test_empty_strings_treated_as_unset(self):
        s = _settings(project_ref="", supabase_jwks_url="")
        assert s.jwks_url is None


class TestCorsOrigins:
    def test_split_and_strip(self):
        s = _settings(cors_origins="http://a.test, http://b.test ,http://c.test")
        assert s.cors_origins_list == ["http://a.test", "http://b.test", "http://c.test"]

    def test_single_origin(self):
        assert _settings(cors_origins="http://a.test").cors_origins_list == ["http://a.test"]

    def test_empty_segments_dropped(self):
        assert _settings(cors_origins="http://a.test,, ,").cors_origins_list == ["http://a.test"]


class TestEnvironment:
    @pytest.mark.parametrize("env", ["local", "development", "staging", "production"])
    def test_literal_accepts_documented_values(self, env, make_settings):
        # Regression guard: ENVIRONMENT=development used to crash importers
        # with a ValidationError at import time (see comment in config.py).
        s = make_settings(ENVIRONMENT=env)
        assert s.ENVIRONMENT == env

    def test_unknown_environment_rejected(self, make_settings):
        with pytest.raises(ValidationError):
            make_settings(ENVIRONMENT="prod")

    def test_is_development(self):
        assert _settings(environment="development").is_development is True
        assert _settings(environment="production").is_development is False


class TestJobStore:
    def test_defaults_to_memory(self):
        s = _settings()
        assert s.job_store == "memory"
        assert s.supabase_jobs_table == "conversion_jobs"

    def test_env_selects_supabase(self, make_settings):
        s = make_settings(JOB_STORE="supabase")
        assert s.job_store == "supabase"
