# Corpora Example App

The reference client for the `corpora-py` API: convert documents into
Text-Fabric corpora, browse and read what you've published, and chat with an
AI that queries the corpus through MCP tools. One codebase ships two ways —
a native desktop app via Electrobun, and a static SPA on the web
([corpora-py-example.vercel.app](https://corpora-py-example.vercel.app)).

## Features

- **Convert** — EPUB, HTML, XML, TEI, PDF and plain text → Text-Fabric `.corpus`
  archives, with live job status over WebSocket (and polling fallback)
- **Explore & publish** — browse the `.corpus` archives on the Hugging Face Hub
- **Corpus detail & reader** — edit manifest metadata, browse the section index,
  read paginated passages (see [the flow](#corpus-detail-flow))
- **Chat** — an in-browser agent that loads a published corpus and queries it
  through the backend's MCP tools; bring your own Anthropic key, or use the
  free demo model with none
- **Capability-aware UI** — write affordances are *hidden*, not left to 403,
  when the backend reports a read-only Hub
- **Dark mode** and **desktop-native** packaging (macOS/Windows/Linux)

## Quick Start

### Prerequisites

- Bun 1.x (or Node.js 18+)
- A running `corpora-py` backend — from the monorepo root: `uv sync && AUTH_REQUIRED=false uv run corpora-api`

### Installation

```bash
cd example
bun install
```

### Development

```bash
bun run vite:dev      # web dev server (proxies /api/gateway to the real AI Gateway)
bun run desktop:dev   # Electrobun desktop app, watch mode
bun run typecheck     # react-router typegen + tsc
bun run format        # prettier
```

### Build

```bash
bun run vite:build    # static SPA → dist/client
bun run build:canary  # desktop bundle (canary env)
```

## Environment

| Variable | Where | Purpose |
|---|---|---|
| `VITE_API_URL` | build time | Backend base URL. Vite **inlines** it, so it must be set before the build or the bundle falls back to `http://127.0.0.1:8000` (`app/lib/types/socket.ts`). |
| `AI_GATEWAY_API_KEY` | server | Optional explicit credential for the free-model proxy; otherwise the deployment's OIDC token is used. |

The Supabase token on the Settings page is **optional** — `apiFetch` attaches a
Bearer header only when one is stored, so the demo works with none. An Anthropic
key there is likewise optional; without it the chat uses the free demo model.

## Deploy the web example to Vercel

The same React Router app that ships inside Electrobun serves on the web as a
static SPA (`react-router.config.ts` sets `ssr: false`), deployed as a **second
Vercel project on this same repo**, distinct from the Python API project
(`corpora-py`, deployed from the repo root). Both are wired to the repo's Git
integration, so **a push that redeploys the API also redeploys the web example**
— no GitHub Actions, no deploy chaining.

`example/vercel.json` pins the build so the project works the moment it's linked:

- `framework: null`, `installCommand: bun install`,
  `buildCommand: react-router build`, `outputDirectory: dist/client` — plain
  static output, **not** the `@vercel/react-router` SSR preset (the build also
  emits `dist/server/`; it's intentionally ignored so no React Router server
  function is deployed).
- The SPA rewrite is `/((?!api/).*) → /index.html`, not a bare catch-all: the
  negative lookahead keeps `api/gateway/[path].ts` reachable as a real Node
  function. Assets under `/assets/*` still serve directly (the filesystem is
  checked before rewrites).

### One-time setup (Vercel dashboard or CLI)

1. **Create the project** from this GitHub repo → set **Root Directory** to
   `example`. Vercel reads `example/vercel.json` from there.
2. **Production Branch** → `main` (match the API project so both promote on the
   same push).
3. **Environment variable** — `VITE_API_URL = https://corpora-py.vercel.app`
   (Production + Preview). Build-time; see the table above.
4. **Domain** — assign `corpora-py-example.vercel.app` to the project's
   production deployment.
5. Trigger the first deploy (push, or **Redeploy**) and confirm the app is
   served statically (an `index.html` at the root, assets under `/assets/`) with
   exactly **one** function — `api/gateway/[path]` — and no React Router server
   function.

### Free-model chat proxy (`api/gateway/[path].ts`)

The chat agent runs in the visitor's browser. With no Anthropic key of its own
it calls this deployment's proxy, which forwards to the Vercel AI Gateway using
the **deployment's** credential — which must never reach the browser. Two rules
keep that safe to expose publicly:

- only models in `ALLOWED_MODELS` (free, $0/token) pass through — checked from
  the `ai-language-model-id` header, before any upstream call;
- only the two endpoints the browser provider actually uses (`language-model`,
  `config`) are reachable. It is not a general gateway proxy.

`bun run vite:dev` doesn't run the function at all — `vite.config.ts` proxies
`/api/gateway` to the real gateway with the same env fallback.

### Backend (API) configuration for the public demo

For the public web example to load corpora without a signed-in Supabase session,
set these on the **API** project (`corpora-py`) in Vercel — not on this one:

| Env var | Value | Why |
|---|---|---|
| `AUTH_REQUIRED` | `false` | Opens reads/queries/conversions to anonymous visitors (the default `true` fail-closes to 401). |
| `HF_READ_ONLY` | `true` | **Locks the Hub.** With auth off, this is what keeps the public from mutating your Hub repo. |
| `HF_STORAGE_REPO` | your Hub repo/bucket | Where the `.corpus` archives live; without it `/storage` 503s. |
| `HF_TOKEN` | a Hub token, **read-only scope** | Auth for reading the (private) storage repo. |
| `HF_HOME` | `/tmp/huggingface` | The default cache path is read-only on Vercel Functions — without this every stored-corpus read 500s. |

> **The hardest guarantee is the token, not the code.** `AUTH_REQUIRED=false` and
> `HF_READ_ONLY=true` must *both* be set — set only the first and a
> write-capable token leaves your Hub wide open. A **fine-grained read-only
> `HF_TOKEN`** removes that footgun entirely: Hugging Face itself refuses every
> write regardless of app code. Mint one at Settings → Access Tokens
> (fine-grained, read-only on the storage repo). Publish from your own machine
> with a separate write token that never ships to the deployment.

**Read-only guarantee (`HF_READ_ONLY=true`).** Every Hub write is refused across
both API surfaces: the write routes (`POST /storage`, `DELETE /storage/{f}`,
`PATCH /storage/{f}/manifest`, `PATCH …/nodes/{n}`) return **403**, and the four
write MCP tools (`storage_upload_corpus`, `storage_delete_corpus`,
`corpus_manifest_update`, `corpus_node_annotate`) are never registered — so
nothing on the public API can push to, delete from, or re-upload the repo. Reads,
downloads, conversions and corpus queries are unaffected. You keep publishing
from your own machine (`HF_READ_ONLY` unset) to the **same** repo the demo reads.

Consequence for the UI: the app asks `GET /capabilities` (unauthenticated;
reports `auth_required` and `hub_writable`) and, when the Hub is read-only, omits
the **Publish to Hugging Face** button and the corpus **Edit** metadata button
entirely (`app/lib/capabilities.ts`). Chat **"Fix"** chips still get a
missing-tool response, since those write tools aren't registered.

Exposures to accept (or address) before going live — read-only mode covers Hub
writes, **not** these:

- **Anonymous compute.** With auth off, `POST /convert` is reachable by anyone
  and pins a CPU for up to the 300s function limit. Consider disabling public
  conversion, or putting the API behind Vercel's firewall / rate limiting.
  (`/ingest` already 503s on Vercel.)
- **Job scoping off.** Conversion-job polling/downloads no longer scope to their
  submitter, so any job id is visible to anyone.
- **Private repo, public reads.** The server reads the (private) Hub repo with
  its own token and serves its contents to every visitor.

## Project Structure

```
api/
└── gateway/[path].ts     # Node function: free-model AI Gateway proxy (web deploy only)

app/
├── routes/               # React Router pages (tree in app/routes.ts)
│   ├── home.tsx          #   dashboard
│   ├── explore.tsx       #   browse/search .corpus archives on the Hub
│   ├── chat.tsx          #   in-browser agent over the backend's MCP tools
│   ├── settings.tsx      #   Anthropic / Supabase keys, backend probe
│   └── corpus/
│       ├── upload.tsx    #   upload dialog
│       ├── convert.tsx   #   conversion pipeline UI
│       ├── layout.tsx    #   corpus detail layout (breadcrumb + Detail/View tabs)
│       ├── detail.tsx    #   manifest metadata (editable) + section index
│       └── view.tsx      #   paginated reader with section picker
├── components/
│   ├── ai-elements/      #   conversation, message, prompt-input, tool call UI
│   ├── chat/             #   ChatView, corpus picker, corpus loading
│   ├── convert/          #   upload + job status
│   ├── ui/  reui/  beste/ #  shadcn (base-vega) + ReUI registry components
│   └── workspace/        #   corpus workspace shell
└── lib/
    ├── agent-model.ts    #   own-key vs free-demo model selection
    ├── capabilities.ts   #   GET /capabilities → hide dead write actions
    ├── corpus-detail.ts  #   typed client + pure helpers for the detail endpoints
    ├── atoms/  hooks/  types/  uploads/
    └── settings.ts       #   stored keys, bound fetch

bun/                      # Electrobun main process: entry, python bridge, websocket, storage
public/                   # static assets
dist/                     # built app & web output
```

## Corpus detail flow

Browsing a stored archive runs `explore → detail → view`:

1. **`/explore`** lists the `.corpus` archives published to the Hub. Each row's
   **Details** action navigates to `/corpus/:id`, where `:id` is the archive
   filename minus the trailing `.corpus`, URL-encoded.
2. **`/corpus/:id`** (`routes/corpus/layout.tsx`) is a shared layout: an
   `Explore → <name>` breadcrumb plus **Detail** / **View** tabs.
3. **`/corpus/:id`** → `routes/corpus/detail.tsx` — an editable manifest metadata
   card (PATCHes the archive on the Hub) and a section-index card linking into
   the reader.
4. **`/corpus/:id/view`** — a paginated passage reader with a section picker; the
   current section lives in the URL as `?ref=`.

All four screens talk to the backend through the typed client and pure helpers in
`app/lib/corpus-detail.ts`, which target `/storage/{filename}/{manifest,index,content}`
(`{filename}` = `:id` with `.corpus` re-appended). Server side:
[`packages/admin/README.md`](../packages/admin/README.md).

## Tech Stack

| Layer | Choice |
|---|---|
| Framework | React 19 + React Router 8 (framework mode, `ssr: false`) |
| Desktop | Electrobun 1.18.4-beta |
| AI | AI SDK v7 (`ai`, `@ai-sdk/react`, `@ai-sdk/mcp`, `@ai-sdk/anthropic`) — a browser-side `ToolLoopAgent` over the backend's MCP server |
| UI | shadcn (`base-vega` style) on Base UI, plus the ReUI registry; Lucide icons |
| Styling | Tailwind CSS 4 |
| State | Jotai (+ Immer) |
| Animation | Motion (Framer Motion) |
| Markdown | Streamdown (code, math, mermaid, CJK) with Shiki |
| Build | Vite 8 + React Router preset |
| Language | TypeScript 6 |

### Adding UI components

```bash
bunx shadcn@latest add <component-name>     # config in components.json
```

## Scripts

| Command | Purpose |
|---|---|
| `vite:dev` | Web dev server |
| `desktop:dev` | Electrobun app (watch) |
| `vite:build` | Build static SPA → `dist/client` |
| `build:canary` | Build desktop canary release |
| `typecheck` | `react-router typegen` + `tsc` |
| `test` | `bun test` |
| `format` | Prettier |
| `clean` | Remove build artifacts |

## Contributing

Part of the `corpora-py` monorepo — see the root [`README.md`](../README.md) and
`CLAUDE.md` for workspace commands and the branching model.

## License

See the parent repository [LICENSE](../LICENSE).
