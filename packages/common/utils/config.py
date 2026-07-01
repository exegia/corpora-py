import os
from typing import Literal

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

    PROJECT_NAME = "Corpora API"
    PROJECT_DESC = "FastAPI project to be loaded as a wheel, docker and/or server."
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


settings = Settings()
