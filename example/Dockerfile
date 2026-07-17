# example/Dockerfile — dev container image for the ElectroBun example app.
#
# Built from the REPO ROOT (not example/) so the local Python workspace can be
# installed next to the app — .github/workflows/demo-app-docker.yml passes
# `context: .` with `file: example/Dockerfile`:
#
#   docker build -f example/Dockerfile -t corpora-example-dev .
#
# What's inside:
#   - Bun (JS runtime for the React Router / ElectroBun app in example/)
#   - the local Python library as an *editable* uv venv at /workspace/.venv
#     (corpora-common + corpora-mcp + corpora-admin + the corpora-py umbrella)
#   - DEV_PYTHON_BIN pointing at the venv python, so the app's PythonBridge
#     (example/bun/python-bridge.ts) uses it instead of looking for the
#     "frozen" embedded runtime — no embedded Python is bundled in this image.
#
# Run the web dev server (http://localhost:5173):
#   docker run --rm -p 5173:5173 corpora-example-dev
# Or use it as an interactive dev shell:
#   docker run --rm -it corpora-example-dev bash

FROM python:3.13-slim

LABEL org.opencontainers.image.title="corpora-py example (dev)" \
      org.opencontainers.image.description="Dev container for the ElectroBun example app: Bun + editable corpora-py venv" \
      org.opencontainers.image.source="https://github.com/exegia/corpora-py"

# Bun and uv, copied from their official images (no curl|sh installers).
COPY --from=oven/bun:1 /usr/local/bin/bun /usr/local/bin/bun
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
RUN ln -s /usr/local/bin/bun /usr/local/bin/bunx

# Optional PEM bundle for TLS-intercepting egress proxies (dev sandboxes /
# corporate networks). CI leaves this unset. Local use:
#   docker build --build-arg EXTRA_CA_CERTS="$(cat proxy-ca.pem)" ...
ARG EXTRA_CA_CERTS=""
RUN if [ -n "$EXTRA_CA_CERTS" ]; then \
        printf '%s\n' "$EXTRA_CA_CERTS" > /usr/local/share/ca-certificates/extra-ca.crt \
        && update-ca-certificates; \
    fi
# Debian's default bundle (which update-ca-certificates above feeds into).
# Harmless when EXTRA_CA_CERTS is unset; lets uv and bun trust the extra CA
# when it is set.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

# git for convert_to_corpus()'s `.corpus` version-history snapshot;
# libxml2/libxslt1.1 for lxml/beautifulsoup4 (same as dockerfiles/Dockerfile);
# nodejs because the react-router CLI (`bun run vite:dev`) declares a node
# shebang — under bun's node-shim its typegen crashes ("generate is not a
# function", a @babel/generator CJS-interop difference), while under real
# node it works. Bun stays the package manager / script runner.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git libxml2 libxslt1.1 nodejs \
    && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

# ── Python workspace → editable venv at /workspace/.venv ─────────────────────
# Manifests + sources first; app code changes shouldn't bust these layers.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY packages/ packages/
COPY src/corpora_py/ src/corpora_py/
RUN uv sync --frozen --no-dev

# ── Example app: dependencies, then sources ───────────────────────────────────
WORKDIR /workspace/example
COPY example/package.json example/bun.lock ./
RUN bun install --frozen-lockfile
COPY example/ ./

# PythonBridge dev override (see example/bun/python-bridge.ts). Do NOT set
# DEV_PYTHON_HOME here — PYTHONHOME breaks venv interpreters; the venv python
# resolves its own home.
ENV DEV_PYTHON_BIN=/workspace/.venv/bin/python3 \
    PATH="/workspace/.venv/bin:${PATH}"

EXPOSE 5173
# Web dev server; --host makes Vite bind 0.0.0.0 so -p 5173:5173 works.
# (The ElectroBun desktop shell itself can't run headless in a container.)
CMD ["bun", "run", "vite:dev", "--host", "0.0.0.0"]
