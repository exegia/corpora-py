"""Environment-backed constants loaded from `.env.{environment}` at import time."""

from __future__ import annotations
from pathlib import Path
from config import settings

from platformdirs import PlatformDirs

PROJECT_ROOT = Path(__file__).resolve().parents[3]
application_support = PlatformDirs("exegia")

# Application
ENVIRONMENT = settings.environment
CORS_ORIGINS = settings.cors_origins
CORS_ORIGINS_LIST = settings.cors_origins_list

CERT_DIR = Path("app")
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"

# AI
OPENAI_KEY = settings.open_ai_key

__all__ = [
    "CERT_DIR",
    "CERT_FILE",
    "KEY_FILE",
    "CORS_ORIGINS",
    "PROJECT_ROOT",
    "CORS_ORIGINS_LIST",
    "ENVIRONMENT",
    "OPENAI_KEY",
    "application_support"
]
