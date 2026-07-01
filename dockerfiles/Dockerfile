# Dockerfile (umbrella)
# Full-featured image: combined FastAPI app (MCP server + admin/conversion API).
# Equivalent to installing corpora-py (all workspace packages).
#
# Build:
#   docker build -t corpora-py .
#
# Run the combined app (MCP at /mcp, conversion API at /convert):
#   docker run -p 8000:8000 \
#     -v ~/.exegia/datasets:/data/datasets:ro \
#     corpora-py
#
# Run conversion tools directly (bypassing the HTTP API):
#   docker run -it \
#     -v ~/.exegia/datasets:/data/datasets \
#     -v ~/sources:/data/sources:ro \
#     --entrypoint python corpora-py \
#     -c "from admin.converters import convert_epub_to_tf; convert_epub_to_tf('/data/sources/book.epub', '/data/datasets/out')"

# ── Stage 1: build all workspace wheels ──────────────────────────────────────
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock* README.md ./
COPY packages/common  packages/common
COPY packages/mcp     packages/mcp
COPY packages/admin   packages/admin
COPY src/corpora_py   src/corpora_py

# Build all wheels so pip can resolve workspace deps without hitting PyPI
RUN uv build --package corpora-common --wheel --out-dir /wheels/ && \
    uv build --package corpora-mcp    --wheel --out-dir /wheels/ && \
    uv build --package corpora-admin  --wheel --out-dir /wheels/ && \
    uv build --wheel --out-dir /wheels/

# Install everything (corpora-py umbrella, which pulls in text-fabric via corpora-admin)
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --find-links /wheels \
        corpora-py

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim

LABEL org.opencontainers.image.title="corpora-py" \
      org.opencontainers.image.description="Corpora platform — combined MCP server + admin conversion API" \
      org.opencontainers.image.source="https://github.com/exegia/corpora-py"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    UVICORN_HOST=0.0.0.0

VOLUME ["/data/datasets", "/data/sources"]
EXPOSE 8000

# Goes through `corpora_py.app.main()` (not a raw `uvicorn ...` command) so
# its `workers=1` guard (JobManager is an in-process singleton -- see
# jobs.py) can't be silently bypassed by editing this line. `UVICORN_HOST`
# above makes main() bind 0.0.0.0 instead of its local-dev-only 127.0.0.1
# default.
ENTRYPOINT ["corpora-api"]
