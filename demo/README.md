# React + Tailwind + Vite Electrobun Template

A fast Electrobun desktop app template with React, Tailwind CSS, and Vite for hot module replacement (HMR).

## Getting Started

```bash
# Install dependencies
bun install

# Development without HMR (uses bundled assets)
bun run dev

# Development with HMR (recommended)
bun run dev:hmr

# Build for production
bun run build

# Build for production release
bun run build:prod
```

## How HMR Works

When you run `bun run dev:hmr`:

1. **Vite dev server** starts on `http://localhost:5173` with HMR enabled
2. **Electrobun** starts and detects the running Vite server
3. The app loads from the Vite dev server instead of bundled assets
4. Changes to React components update instantly without full page reload

When you run `bun run dev` (without HMR):

1. Electrobun starts and loads from `views://mainview/index.html`
2. You need to rebuild (`bun run build`) to see changes

## Project Structure

```
├── src/
│   ├── bun/
│   │   └── index.ts        # Main process (Electrobun/Bun)
│   └── mainview/
│       ├── App.tsx         # React app component
│       ├── main.tsx        # React entry point
│       ├── index.html      # HTML template
│       └── index.css       # Tailwind CSS
├── electrobun.config.ts    # Electrobun configuration
├── vite.config.ts          # Vite configuration
├── tailwind.config.js      # Tailwind configuration
└── package.json
```

## Customizing

- **React components**: Edit files in `src/mainview/`
- **Tailwind theme**: Edit `tailwind.config.js`
- **Vite settings**: Edit `vite.config.ts`
- **Window settings**: Edit `src/bun/index.ts`
- **App metadata**: Edit `electrobun.config.ts`

## Developing with Docker + SSH (recommended for consistent Python + Bun env)

This repo provides a first-class Docker dev environment so the ElectroBun demo can use the local Python `corpora-py` library (split into `common` / `mcp` / `admin` workspaces, importable as `common` / `corpora_mcp` / `admin`) without manual setup.

### 1. Start the container

```bash
# From repo root
docker compose -f demo/docker/docker-compose.yml up --build -d
```

### 2. Connect from your IDE via SSH

Add to your `~/.ssh/config`:

```
Host corpora-demo
  HostName localhost
  Port 2222
  User dev
```

Then in VS Code / Cursor:

- Command Palette → **Remote-SSH: Connect to Host** → `corpora-demo`

Default password is `dev` (change it or use key auth).

**Passwordless login (recommended):**

```bash
export SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"
docker compose -f demo/docker/docker-compose.yml up --build -d
```

### 3. Inside the container

```bash
cd /workspace/demo/docker

# Normal dev (no HMR)
bun run dev

# Recommended (Vite HMR + ElectroBun)
bun run dev:hmr
```

The Python bridge automatically uses a dev Python that has the local library installed editable (`import common`, `import corpora_mcp`, `import admin` just work).

### 4. Rebuilding the Python side

Because we use an editable install, changes to `packages/common/src/common/**/*.py`, `packages/mcp/src/corpora_mcp/**/*.py` or `packages/admin/src/admin/**/*.py` are reflected immediately (restart the Bun process if you changed top-level imports).

### Files

- `demo/docker/Dockerfile`
- `demo/docker/docker-compose.yml`
- `demo/docker/scripts/docker-entrypoint.sh`
- `.github/workflows/demo-app-docker.yml` (builds + publishes the dev image to GHCR)

The container also exposes the Vite dev server on port 5173 (useful for debugging the webview even if you don't forward the native window).
