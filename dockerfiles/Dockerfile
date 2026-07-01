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
#     -m admin.utils.convert_epub_to_tf /data/sources/book.epub /data/datasets/out

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
    ENVIRONMENT=production

VOLUME ["/data/datasets", "/data/sources"]
EXPOSE 8000

# `corpora_py.app.main()` binds 127.0.0.1 (correct for local `corpora-api`
# usage outside a container) — invoke uvicorn directly here so the server is
# actually reachable from outside the container.
ENTRYPOINT ["uvicorn", "corpora_py.app:app", "--host", "0.0.0.0", "--port", "8000"]
