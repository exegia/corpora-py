# Corpora Example App

A desktop application for converting, browsing, and querying Text-Fabric corpora. Built with React Router 8, Electrobun,
and TypeScript.

## Features

- **Convert corpora** — Transform EPUB, HTML, PDF, and TEI documents into Text-Fabric datasets
- **Browse datasets** — View Text-Fabric corpora with full API access via the MCP server
- **Corpus detail & reader** — Open any stored `.corpus` archive to edit its manifest metadata, browse its section
  index, and read passages (see the flow below)
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
├── routes/              # React Router pages (see app/routes.ts for the tree)
│   ├── home.tsx        # Dashboard with quick actions
│   ├── explore.tsx     # Browse/search .corpus archives on the Hub
│   ├── corpus/
│   │   ├── upload.tsx  # Upload dialog for new corpora
│   │   ├── convert.tsx # Conversion pipeline UI
│   │   ├── layout.tsx  # Corpus detail layout (breadcrumb + Detail/View tabs)
│   │   ├── detail.tsx  # Corpus metadata (editable) & section index
│   │   └── view.tsx    # Corpus reader view (paginated, section picker)
│   └── +types/         # Auto-generated type definitions
├── components/         # Reusable UI components
├── lib/               # Utilities (routing, theme, sounds)
│   └── corpus-detail.ts # Typed client + pure helpers for the detail endpoints
└── app.css            # Global styles (Tailwind + custom)

bun/                    # Backend integration
├── index.ts           # Electrobun entry point
├── python-bridge.ts   # Python subprocess management
├── websocket.ts       # Real-time updates
└── storage.ts         # Local data persistence

public/                # Static assets
dist/                  # Built app & web output
```

## Corpus detail flow

Browsing a stored archive runs `explore → detail → view`:

1. **`/explore`** (`routes/explore.tsx`) lists the `.corpus` archives published to the Hub. Each row has a **Details**
   action that navigates to `/corpus/:id`, where `:id` is the archive filename minus the trailing `.corpus`,
   URL-encoded.
2. **`/corpus/:id`** (`routes/corpus/layout.tsx`) is a shared layout: an `Explore → <name>`
   breadcrumb plus **Detail** / **View** tabs. Its index route is the detail tab.
3. **`/corpus/:id`** → **`routes/corpus/detail.tsx`** — an editable manifest metadata card (PATCHes the archive on the
   Hub) and a section-index card whose entries link into the reader.
4. **`/corpus/:id/view`** (`routes/corpus/view.tsx`) — a paginated passage reader with a section picker; the current
   section is kept in the URL as `?ref=`.

All four screens talk to the backend through the typed client and pure helpers in
`app/lib/corpus-detail.ts`, which target the `/storage/{filename}/{manifest,index,content}`
endpoints (`{filename}` = `:id` with `.corpus` re-appended). See `packages/admin/CLAUDE.md` for the server side.

## Tech Stack

- **Framework** — React 19 with React Router 8 (framework mode)
- **Desktop** — Electrobun 1.18.4-beta
- **UI Components** — [shadcn/ui](https://ui.shadcn.com) (copy-paste Radix UI + Tailwind CSS)
- **Styling** — Tailwind CSS 4
- **State** — Jotai with Immer for immutable updates
- **Animation** — Framer Motion
- **Build** — Vite with React Router preset
- **Language** — TypeScript 6
- **Backend** — Python via subprocess bridge (corpora-mcp/corpora-admin)

## UI Components (shadcn)

This project uses [shadcn/ui](https://ui.shadcn.com) for all React components. Components are copy-pasted into
`app/components/ui/` and styled with Tailwind CSS.

### Adding new components

```bash
npx shadcn-ui@latest add <component-name>
```

Common components: `button`, `card`, `dialog`, `input`, `select`, `table`, `toast`, etc.
See [shadcn/ui docs](https://ui.shadcn.com/docs/components/button) for usage.

## Environment

The app connects to the Python backend (`corpora-py` workspace) to:

- Load Text-Fabric corpora
- Handle EPUB/HTML/PDF conversions
- Provide MCP server access

Set `VITE_PYTHON_PORT` to override the backend connection (default: `8000`).

## Scripts

| Command        | Purpose                            |
|----------------|------------------------------------|
| `vite:dev`     | Start web dev server               |
| `desktop:dev`  | Start Electrobun app (watch)       |
| `vite:build`   | Build web bundle                   |
| `build:canary` | Build desktop canary release       |
| `typecheck`    | Check TypeScript & generate routes |
| `format`       | Format code with Prettier          |
| `clean`        | Remove build artifacts             |

## Contributing

This is part of the `corpora-py` monorepo. See the root `CLAUDE.md` for workspace commands and contribution guidelines.

## License

See the parent repository LICENSE.
