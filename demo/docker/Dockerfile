# demo/app/Dockerfile
# Development container for the ElectroBun + Python demo app.
# - Full Bun + ElectroBun dev environment
# - Python 3.13 + uv + the local corpora-py / exegia library installed editable
# - OpenSSH server so IDEs (VS Code, Cursor, etc.) can connect via Remote-SSH
#
# Usage (recommended with docker-compose):
#   docker compose -f demo/app/docker-compose.yml up --build
#   # Then from host:
#   ssh -p 2222 dev@localhost
#
# Or for IDE:
#   Add to ~/.ssh/config:
#     Host corpora-demo-dev
#       HostName localhost
#       Port 2222
#       User dev
#   Then: Remote-SSH > Connect to Host > corpora-demo-dev

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_PREFERENCE=only-managed

# Base tools + SSH + Python build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    curl \
    ca-certificates \
    unzip \
    tar \
    git \
    # Node will be installed via nodesource for a modern version (required by some CLIs like dotenvx) \
    build-essential \
    pkg-config \
    libssl-dev \
    # For GUI / X11 forwarding if you want to run the native window (optional)
    xvfb \
    libgtk-3-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2t64 \
    libpango-1.0-0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Install modern Node.js (20+) via nodesource - required for some package CLIs (e.g. dotenvx)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create SSH run dir
RUN mkdir -p /var/run/sshd

# Install uv (goes to /root/.local/bin by default)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# Make uv available system-wide
RUN cp /root/.local/bin/uv /usr/local/bin/uv && chmod +x /usr/local/bin/uv

# Install Bun system-wide (so all users including 'dev' can use it)
RUN curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash

# Ensure /usr/local/bin is early in PATH for all users (login + non-login shells)
# Additional runtime setup happens in docker-entrypoint.sh + /etc/profile.d/corpora-dev.sh
ENV PATH="/usr/local/bin:${PATH}"

# Create a dedicated dev user (non-root is better)
RUN useradd -m -s /bin/bash -G sudo dev \
    && echo 'dev:dev' | chpasswd \
    && echo 'dev ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

# Configure SSH for dev (password works for first login; prefer keys)
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config \
    && sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config

# Prepare workspace
RUN mkdir -p /workspace
WORKDIR /workspace

# Expose SSH + Vite HMR port (the actual desktop window may need X forwarding or be run on host)
EXPOSE 22 5173

# Entrypoint handles venv creation for Python lib + SSH key injection + sshd
COPY demo/app/scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Default: run sshd in foreground. Developer SSH's in and runs `bun run dev` / `bun run dev:hmr`
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/usr/sbin/sshd", "-D", "-e"]
