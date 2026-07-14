# Corpora Example App

A desktop application for converting, browsing, and querying Text-Fabric corpora. Built with React Router 8, Electrobun, and TypeScript.

## Features

- **Convert corpora** — Transform EPUB, HTML, PDF, and TEI documents into Text-Fabric datasets
- **Browse datasets** — View Text-Fabric corpora with full API access via the MCP server
- **Query support** — Use Claude or other AI models to query your corpus data
- **Dark mode** — Light and dark theme support with persistent storage
- **Desktop-native** — Runs as a native macOS/Windows/Linux application via Electrobun

## Quick Start

### Prerequisites

- Node.js 18+ (or Bun 1.x)
- `corpora-py` package (parent workspace)

### Installation

```bash
# From the monorepo root
uv sync

# Or manually:
cd example
bun install  # or npm install
```

### Development

```bash
# Start the Vite dev server (web-based)
bun run vite:dev

# Start the Electrobun desktop app (watch mode)
bun run desktop:dev

# Type-check and generate routes
bun run typecheck

# Format code
bun run format
```

### Build

```bash
# Build for web (Vite)
bun run vite:build

# Build desktop app (canary environment)
bun run build:canary
```

## Project Structure

```
app/
├── routes/              # React Router pages
│   ├── home.tsx        # Dashboard with quick actions
│   ├── corpus/
│   │   ├── upload.tsx  # Upload dialog for new corpora
│   │   ├── convert.tsx # Conversion pipeline UI
│   │   ├── layout.tsx  # Corpus detail layout
│   │   ├── detail.tsx  # Corpus metadata & stats
│   │   └── view.tsx    # Corpus reader view
│   └── +types/         # Auto-generated type definitions
├── components/         # Reusable UI components
├── lib/               # Utilities (routing, theme, sounds)
└── app.css            # Global styles (Tailwind + custom)

bun/                    # Backend integration
├── index.ts           # Electrobun entry point
├── python-bridge.ts   # Python subprocess management
├── websocket.ts       # Real-time updates
└── storage.ts         # Local data persistence

public/                # Static assets
dist/                  # Built app & web output
```

## Tech Stack

- **Framework** — React 19 with React Router 8 (framework mode)
- **Desktop** — Electrobun 1.18.4-beta
- **Styling** — Tailwind CSS 4 + Base UI components
- **State** — Jotai with Immer for immutable updates
- **Animation** — Framer Motion
- **Build** — Vite with React Router preset
- **Language** — TypeScript 6
- **Backend** — Python via subprocess bridge (corpora-mcp/corpora-admin)

## Environment

The app connects to the Python backend (`corpora-py` workspace) to:
- Load Text-Fabric corpora
- Handle EPUB/HTML/PDF conversions
- Provide MCP server access

Set `VITE_PYTHON_PORT` to override the backend connection (default: `8000`).

## Scripts

| Command | Purpose |
|---------|---------|
| `vite:dev` | Start web dev server |
| `desktop:dev` | Start Electrobun app (watch) |
| `vite:build` | Build web bundle |
| `build:canary` | Build desktop canary release |
| `typecheck` | Check TypeScript & generate routes |
| `format` | Format code with Prettier |
| `clean` | Remove build artifacts |

## Contributing

This is part of the `corpora-py` monorepo. See the root `CLAUDE.md` for workspace commands and contribution guidelines.

## License

See the parent repository LICENSE.
