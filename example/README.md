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

## Deploy the web example to Vercel

The same React Router app that ships inside Electrobun can be served on the web
as a static SPA (`react-router.config.ts` sets `ssr: false`). It is deployed to
**`corpora-py-example.vercel.app`** as a **second Vercel project on this same
repo**, distinct from the Python API project (`corpora-py`, deployed from the
repo root).

Both projects are wired to the repo's Git integration, so **a push that
redeploys the API also redeploys the web example** — no GitHub Actions, no
deploy chaining. `example/vercel.json` pins the static-SPA build so the project
works the moment it is linked:

- `framework: null`, `buildCommand: react-router build`,
  `outputDirectory: dist/client` — plain static output, **not** the
  `@vercel/react-router` SSR preset (the build also emits `dist/server/`; it is
  intentionally ignored so Vercel never deploys a server function).
- A catch-all rewrite (`/(.*) → /index.html`) hands unknown paths to the client
  router; real assets under `/assets/*` still serve directly (the filesystem is
  checked before rewrites).

### One-time setup (Vercel dashboard or CLI)

1. **Create the project** from this GitHub repo → set **Root Directory** to
   `example`. Vercel reads `example/vercel.json` from there.
2. **Production Branch** → `dev` (match the API project so both promote
   production on the same push).
3. **Environment variable** — add `VITE_API_URL = https://corpora-py.vercel.app`
   (Production + Preview). This is **build-time**: Vite inlines it, so it must
   exist *before* the build runs, or the bundle falls back to
   `http://127.0.0.1:8000` (see `app/lib/types/socket.ts`).
4. **Domain** — assign `corpora-py-example.vercel.app` to the project's
   production deployment.
5. Trigger the first deploy (push, or **Redeploy**). On that first build,
   confirm it serves the SPA statically (an `index.html` at the root, assets
   under `/assets/`) and does **not** spin up a React Router server function.

### Backend (API) configuration for the public demo

For the public web example to load corpora without a signed-in Supabase
session, set these environment variables on the **API** project (`corpora-py`)
in Vercel — not on this example project:

| Env var           | Value                          | Why                                                                                             |
|-------------------|--------------------------------|-------------------------------------------------------------------------------------------------|
| `AUTH_REQUIRED`   | `false`                        | Opens reads/queries/conversions to the anonymous public demo (the default `true` fail-closes to 401). |
| `HF_READ_ONLY`    | `true`                         | **Locks the Hub.** With auth off, this is what keeps the public from mutating your Hub repo — see below. |
| `HF_STORAGE_REPO` | your Hub repo/bucket           | Where the `.corpus` archives live; without it `/storage` 503s.                                   |
| `HF_TOKEN`        | a Hub token, **read-only scope** | Auth for reading the (private) storage repo. **Use a fine-grained read-only token** — see below. |

> **The hardest guarantee is the token, not the code.** `AUTH_REQUIRED=false`
> and `HF_READ_ONLY=true` must *both* be set — set only the first and forget the
> second, and a write-capable token leaves your Hub wide open. A **fine-grained
> read-only `HF_TOKEN`** removes that footgun entirely: Hugging Face itself
> refuses every write regardless of what the app code does, so it backstops the
> whole read-only gate. Mint one at
> huggingface.co → Settings → Access Tokens (fine-grained, read only on the
> storage repo) and use it here. Publish from your own machine with a separate
> write token that never ships to the deployment.

**Read-only guarantee (`HF_READ_ONLY=true`).** Turning auth off would otherwise
open *writes* to everyone. With `HF_READ_ONLY=true` every Hub write is refused
across both API surfaces: HTTP write routes (`POST /storage`,
`DELETE /storage/{f}`, `PATCH /storage/{f}/manifest`, `PATCH …/nodes/{n}`)
return **403**, and the `storage_*` / `corpus_*` **write** MCP tools
(`storage_upload_corpus`, `storage_delete_corpus`, `corpus_manifest_update`,
`corpus_node_annotate`) are not even registered — so nothing on the public API
can push to, delete from, or re-upload the repo. Reads, downloads, conversions,
and corpus queries are unaffected. You keep publishing from your own machine
(run locally with `HF_READ_ONLY` unset / `false`) to the **same** Hub repo; the
demo reads what you publish.

Consequence for the demo UI: the in-browser **Publish** button and the chat
**"Fix"** chips (which call the write tools) will get a 403 / missing-tool
response on the public deployment — expected, since only you can write.

Exposures to accept (or address) before going live — read-only mode covers Hub
writes, **not** these:

- **Anonymous compute.** With auth off, `POST /convert` is reachable by anyone
  and pins a CPU for up to the 300s function limit — visitors can run up your
  Vercel Active-CPU bill (convert → `GET /convert/{id}/download` works without
  ever publishing). This is a cost/abuse *decision*: it may be a legitimate demo
  path, or you may want to disable public conversion / put the API behind
  Vercel's firewall or rate limiting. (`/ingest` already 503s on Vercel.)
- **Job scoping off.** Conversion-job polling/downloads (`GET /convert/{id}`) no
  longer scope to their submitter, so any job id is visible to anyone.
- **Private repo, public reads.** The server reads the (private) Hub repo with
  its own token and serves its contents to every visitor.

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
