import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Supabase
    supabase_url: str = os.getenv("SUPABASE_URL")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    supabase_storage_bucket: str = os.getenv("SUPABASE_STORAGE_BUCKET")

    # Database (Supabase PostgreSQL connection string)
    database_url: str = os.getenv("DATABASE_URL")

    # Datasets
    datasets_base_path: str = os.getenv("DATASETS_BASE_PATH")

    # App
    environment: str = os.getenv("ENVIRONMENT")
    cors_origins: str = os.getenv("CORS_ORIGINS")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


settings = Settings()
