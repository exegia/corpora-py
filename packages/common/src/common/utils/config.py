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
    open_ai_key: str = os.getenv("OPENAI_KEY", "")

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

    # Hugging Face Hub storage for converted .corpus archives (see
    # admin.services.storage). All archives live in the single Hub location
    # named by hf_storage_repo (e.g. "exegia/corpora-archives"); leaving it
    # unset keeps the /storage surface importable but every call fails with a
    # clear "not configured" error rather than a crash at import time. hf_token
    # may stay None -- huggingface_hub then falls back to the HF_TOKEN env var
    # or a cached `hf auth login` token.
    #
    # hf_storage_repo_type selects the backing Hub primitive: a classic repo
    # ("model"/"dataset"/"space") or a "bucket" (Xet-backed object storage,
    # addressed as hf://buckets/<owner>/<name>/...). Buckets are the default:
    # a converted corpus is an opaque .corpus archive, not a browsable dataset,
    # so bucket object storage fits it better than a dataset repo. CorpusStorage
    # routes every operation to the matching huggingface_hub API for the type.
    hf_token: str | None = os.getenv("HF_TOKEN")
    hf_storage_repo: str | None = os.getenv("HF_STORAGE_REPO")
    hf_storage_repo_type: Literal["model", "dataset", "space", "bucket"] = "bucket"
    hf_storage_private: bool = True
    # Read-only Hub mode. When True, every write to the storage repo
    # (upload/delete + the manifest/annotation PATCHes that re-upload the
    # archive) is refused: HTTP write routes return 403 and the `storage_*` /
    # `corpus_*` MCP *write* tools are not registered at all. Reads, downloads,
    # conversions, and queries are unaffected. This is the guard for a PUBLIC
    # deployment reachable without a token (AUTH_REQUIRED=false): the demo can
    # browse/query the Hub, but nobody can mutate it -- the owner keeps
    # publishing locally (AUTH_REQUIRED on / this flag left False) to the same
    # repo. Default False so the desktop sidecar and local dev stay writable;
    # set HF_READ_ONLY=true on the public deployment. It is deliberately NOT
    # coupled to auth_required, so `AUTH_REQUIRED=false` local dev still writes.
    hf_read_only: bool = False

    # Which backend the corpus storage surfaces (/storage REST + MCP + the
    # corpus-detail layer) talk to -- see admin.services.storage's
    # make_corpus_storage(). "huggingface" (default) is the Hub publishing
    # location described above. "supabase" stores .corpus objects in the
    # Supabase Storage bucket below, with object paths scoped per-user by the
    # verified JWT `sub` claim ({sub}/{filename}) so no caller can list or
    # address another user's objects -- the library backend for corpora-web
    # (issue #110 option C). hf_read_only applies to BOTH backends: it is the
    # deployment-wide storage read-only flag, not a Hub-only switch.
    storage_backend: Literal["huggingface", "supabase"] = "huggingface"
    # Base URL of the Supabase project (https://<ref>.supabase.co). Falls back
    # to deriving from project_ref (see supabase_api_url below); set it
    # explicitly for self-hosted/local instances.
    supabase_url: str | None = os.getenv("SUPABASE_URL")
    # Server-side only. Grants full Storage access, bypassing RLS -- the
    # per-user path scoping above is enforced by this service, which is why
    # every request's owner comes from a *verified* JWT and never from client
    # input. Must never appear in client-side config (no VITE_*).
    supabase_service_role_key: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    # Storage bucket holding library .corpus objects (corpora-web writes to
    # the same bucket, e.g. "project-corpora"). Unset keeps the supabase
    # backend importable but every call fails with a clear "not configured"
    # error, matching hf_storage_repo's behavior.
    supabase_storage_bucket: str | None = os.getenv("SUPABASE_STORAGE_BUCKET")

    # Retention window for finished conversion jobs (admin.services.jobs).
    # Terminal jobs older than this are lazily reaped -- removed from the job
    # store and their .corpus result files deleted -- on the next list/submit,
    # bounding disk and memory on a long-running process. 0 (the default)
    # disables reaping, preserving today's keep-forever behavior; set
    # JOB_RETENTION_SECONDS on deployments that need a bounded footprint.
    job_retention_seconds: float = 0

    PROJECT_NAME: ClassVar[str] = "Corpora API"
    PROJECT_DESC: ClassVar[str] = "FastAPI project to be loaded as a wheel, docker and/or server."
    API_V1_STR: str = "/api/v1"
    FRONTEND_HOST: str = "http://localhost:5173"
    # "development" must stay in this list: `is_development`/`.env.development`
    # (see root CLAUDE.md's "Environment / config" section) are the documented
    # local-dev convention, and pydantic-settings binds this field
    # case-insensitively from the same `ENVIRONMENT` env var as the lowercase
    # `environment` field above -- setting `ENVIRONMENT=development` used to
    # raise a `ValidationError` here and crash the entire app at import time
    # (any module importing `common.utils` transitively hits `Settings()`).
    ENVIRONMENT: Literal["local", "development", "staging", "production"] = "local"

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip() for origin in str(self.cors_origins).split(",") if origin.strip()
        ]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def supabase_api_url(self) -> str | None:
        """Base URL for Supabase REST APIs (Storage lives under /storage/v1).

        `supabase_url` wins if set (self-hosted/local instances); otherwise
        derived from `project_ref`, mirroring `jwks_url` below. `None` when
        neither is configured -- the supabase storage backend treats that as
        "not configured", never as a default host.
        """
        if self.supabase_url:
            return self.supabase_url.rstrip("/")
        if self.project_ref:
            return f"https://{self.project_ref}.supabase.co"
        return None

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
