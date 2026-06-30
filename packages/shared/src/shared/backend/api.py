import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.config import settings
from utils.generate_ssl import CERT_FILE, KEY_FILE, generate_ssl_cert

logging.basicConfig(
    level=logging.DEBUG if settings.is_development else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

if settings.is_development:
    generate_ssl_cert()

app = FastAPI(
    title="Exegia API",
    description="Exegia GraphQL API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["Health"], include_in_schema=False)
async def root() -> dict[str, str]:
    return {"message": "Corpora API — see /docs for API reference"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        port=8000,
        reload=True,
        use_colors=True,
        ssl_certfile=str(CERT_FILE),
        ssl_keyfile=str(KEY_FILE),
    )
