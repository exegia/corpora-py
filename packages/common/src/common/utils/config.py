import os
from typing import ClassVar, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    # App
    environment: str | None = os.getenv("ENVIRONMENT")
    cors_origins: str | None = os.getenv("CORS_ORIGINS")
    # AI
    open_ai_key: str = model_config.get("OPENAI_KEY", "")

    # Auth (JWT verification for the combined FastAPI app -- see corpora_py.auth)
    # Defaults to enforced: this ships as a sidecar to a Tauri+Supabase desktop
    # app, and "off by default" is the wrong failure mode for something meant
    # to be reachable on a local port. Opt out explicitly for local dev via
    # AUTH_REQUIRED=false.
    auth_required: bool = True
    # Project ref for the standard hosted Supabase JWKS URL
    # (https://<ref>.supabase.co/auth/v1/.well-known/jwks.json). Ignored if
    # supabase_jwks_url is set explicitly (e.g. for a self-hosted / local
    # OrbStack instance whose JWKS lives at a different host).
    project_ref: str | None = os.getenv("PROJECT_REF")
    supabase_jwks_url: str | None = os.getenv("SUPABASE_JWKS_URL")
    supabase_jwt_audience: str = "authenticated"

    PROJECT_NAME: ClassVar[str] = "Corpora API"
    PROJECT_DESC: ClassVar[str] = "FastAPI project to be loaded as a wheel, docker and/or server."
    API_V1_STR: str = "/api/v1"
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip() for origin in str(self.cors_origins).split(",") if origin.strip()
        ]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def jwks_url(self) -> str | None:
        """Resolve the Supabase JWKS endpoint used to verify auth JWTs.

        `supabase_jwks_url` wins if set (self-hosted/local Supabase, where the
        URL doesn't follow the hosted `<ref>.supabase.co` pattern); otherwise
        it's derived from `project_ref`. `None` if neither is configured --
        callers must treat that as "auth cannot be verified," not "auth is
        optional" (see `corpora_py.auth`).
        """
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.project_ref:
            return f"https://{self.project_ref}.supabase.co/auth/v1/.well-known/jwks.json"
        return None


settings = Settings()
