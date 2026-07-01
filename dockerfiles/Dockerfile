# Dockerfile (umbrella)
# Full-featured image: MCP server + admin/conversion tools.
# Equivalent to installing corpora-py (all workspace packages).
#
# Build:
#   docker build -t corpora-py .
#
# Run MCP server (SSE):
#   docker run -p 8000:8000 \
#     -v ~/.exegia/datasets:/data/datasets:ro \
#     corpora-py --corpus /data/datasets/BHSA --name BHSA --sse 8000
#
# Run conversion tools:
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

COPY pyproject.toml uv.lock* ./
COPY packages/shared  packages/shared
COPY packages/client  packages/client
COPY packages/admin   packages/admin
COPY src/corpora_py   src/corpora_py

# Build all wheels so pip can resolve workspace deps without hitting PyPI
RUN uv build --package corpora-shared-py --wheel --out-dir /wheels/ && \
    uv build --package corpora-client-py --wheel --out-dir /wheels/ && \
    uv build --package corpora-admin-py  --wheel --out-dir /wheels/ && \
    uv build --wheel --out-dir /wheels/

# Install everything (corpora-py umbrella + [full] for text-fabric)
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --find-links /wheels \
        "corpora-py[full]"

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim

LABEL org.opencontainers.image.title="corpora-py" \
      org.opencontainers.image.description="Corpora platform — MCP server + admin tools (full)" \
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

ENTRYPOINT ["cf-mcp"]
CMD ["--help"]
