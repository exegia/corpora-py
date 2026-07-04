"""Environment-backed constants loaded from `.env.{environment}` at import time."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from platformdirs import PlatformDirs
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
application_support = PlatformDirs("exegia")


def _resolve_env_file() -> Path:
    env_name = os.getenv("ENVIRONMENT", "development")
    candidate = PROJECT_ROOT / f".env.{env_name}"
    if candidate.exists():
        return candidate
    return PROJECT_ROOT / ".env.development"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    supabase_url: str = model_config.get("SUPABASE_URL", "")
    supabase_storage_bucket: str = "corpora"
    supabase_publishable_key: str = model_config.get("SUPABASE_PUBLISHABLE_KEY", "")
    supabase_secret_key: str = model_config.get("SUPABASE_SECRET_KEY", "")
    project_ref: str = model_config.get("PROJECT_REF", "")

    # Database
    supabase_db_url: str = model_config.get("SUPABASE_DB_URL", "")
    supabase_db_password: str = model_config.get("SUPABASE_DB_PASSWORD", "")
    supabase_db_user: str = model_config.get("SUPABASE_DB_USER", "")

    # Storage
    supabase_storage_access_key: str = model_config.get(
        "SUPABASE_STORAGE_ACCESS_KEY", ""
    )
    supabase_storage_secret_key: str = model_config.get(
        "SUPABASE_STORAGE_SECRET_KEY", ""
    )

    # Application
    environment: str = model_config.get("ENVIRONMENT", "development")
    cors_origins: str = model_config.get("CORS_ORIGINS", "")

    # AI
    open_ai_key: str = model_config.get("OPENAI_KEY", "")

    # Apple
    development_team: str = model_config.get("DEVELOPMENT_TEAM", "")
    apple_team_id: str = model_config.get("APPLE_TEAM_ID", "")

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.cors_origins:
            return []
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Supabase
PROJECT_REF = settings.project_ref

SUPABASE_STUDIO_URL = "supabase_studio_" + settings.project_ref + ".orb.local"
# API gateway (Kong) — the base URL the Supabase client talks to.
SUPABASE_API_URL = "https://supabase_kong_" + settings.project_ref + ".orb.local"
SUPABASE_STORAGE_BUCKET = settings.supabase_storage_bucket
SUPABASE_PUBLISHABLE_KEY = settings.supabase_publishable_key
SUPABASE_SECRET_KEY = settings.supabase_secret_key

# Database
SUPABASE_DB_URL = "supabase_db_" + settings.project_ref + ".orb.local"
SUPABASE_DB_PASSWORD = settings.supabase_db_password
SUPABASE_DB_USER = settings.supabase_db_user

# Storage
SUPABASE_STORAGE_ACCESS_KEY = settings.supabase_storage_access_key
SUPABASE_STORAGE_SECRET_KEY = settings.supabase_storage_secret_key

# Application
ENVIRONMENT = settings.environment
CORS_ORIGINS = settings.cors_origins
CORS_ORIGINS_LIST = settings.cors_origins_list

# AI
OPENAI_KEY = settings.open_ai_key

# Apple
DEVELOPMENT_TEAM = settings.development_team
APPLE_TEAM_ID = settings.apple_team_id

__all__ = [
    "APPLE_TEAM_ID",
    "CORS_ORIGINS",
    "CORS_ORIGINS_LIST",
    "DEVELOPMENT_TEAM",
    "ENVIRONMENT",
    "OPENAI_KEY",
    "PROJECT_REF",
    "PROJECT_ROOT",
    "SUPABASE_DB_PASSWORD",
    "SUPABASE_DB_URL",
    "SUPABASE_DB_USER",
    "SUPABASE_API_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_STORAGE_ACCESS_KEY",
    "SUPABASE_STORAGE_SECRET_KEY",
    "SUPABASE_STORAGE_BUCKET",
    "Settings",
    "get_settings",
    "settings",
]
