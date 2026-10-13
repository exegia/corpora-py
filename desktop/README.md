# Corpora desktop

Electrobun 2.0.2 + Cottontail + React/Vite, with a desktop-owned Python sidecar. The main process starts the existing
combined `corpora_py.app` backend, waits for `/health`, and exposes its URL and status to React through typed RPC.
Common, admin and MCP run in that one Python process; no separate package servers are needed.

## Development

Install Hutch and Bun and make both available on `PATH`. Desktop scripts run Vite, TypeScript and `concurrently` with
`bun run --bun`, so Node.js is not required. Hutch remains the script runner and dependency installer.

From the repository root:

```sh
cd desktop
hutch run install
hutch run setup        # uv sync --project ..; installs the Python workspace
hutch run dev:hmr      # Vite + Electrobun + managed Python
```

Or use `hutch run dev` for the bundled UI without Vite HMR. Do not separately start `corpora-api`: the desktop starts
its own sidecar on an OS-assigned IPv4 loopback port, so it can coexist with another API on port 8000. The starter UI
displays the backend URL, readiness, auth policy and failures.

Development uses `../.venv/bin/python` (`.venv/Scripts/python.exe` on Windows). To use another interpreter that has the
workspace installed, set `DEV_PYTHON_BIN` to its **absolute** path. Development defaults to `AUTH_REQUIRED=false` only
when the variable is unset. Override it with `AUTH_REQUIRED=true` to exercise the existing Supabase JWT gate. Backend
environment variables are inherited from the desktop process; do not put backend secrets in `VITE_*` variables.

Python source edits require restarting the desktop app. React changes use Vite HMR. Open the Electrobun window, not
localhost:5173 in a standalone browser: the latter has no native RPC bridge or owned Python process.

## Desktop workspace

The shell uses Shark UI's Ark-based **underline tabs**: Dashboard, Jobs, Explorer and Settings. Dashboard displays real
sidecar status, the loopback endpoint, auth policy and RPC response time. Jobs and Explorer are scaffolded views;
conversion submission and library browsing are not wired up there yet.

- The titlebar is a native drag region, with space for the hidden-inset window controls. Theme buttons remain clickable.
- The appearance button cycles **system → light → dark**. Preferences are stored in webview local storage; system mode
  follows OS appearance changes. Settings exposes the same control.
- The bottom status bar stays visible while content scrolls. **Events** expands the latest 50 observed backend state
  changes in this session; it is not a Python console-log stream. Repeated identical poll responses are not logged.
- Settings can pause/resume status checks without stopping the Python process. RPC timing is reported only for
  successful responses, not failed connection attempts.

Run UI utility tests with `bun test src/lib` from `desktop/`.

## Calling Python from React

Use `src/mainview/backend.ts` instead of hardcoding a port:

```ts
import { backendFetch, getBackendUrl, getSidecarStatus } from "./backend";

const status = await getSidecarStatus(); // starting | ready | failed | stopped
const response = await backendFetch("/health");
const apiUrl = await getBackendUrl();    // only resolves once ready
```

The combined API exposes `/convert`, `/storage`, `/refs`, `/validate`, and streamable HTTP MCP at `${apiUrl}/mcp/`. Use
`getBackendUrl()` for the conversion WebSocket URL too. When `status.authRequired` is true, supply the existing Supabase
JWT in `Authorization: Bearer ...` for protected HTTP/MCP requests, or as `?token=...` on conversion WebSocket
connections. The sidecar does not implement sign-in or bypass the backend's auth policy.

## Packaged builds

Bundle a standalone Python runtime first, then package Electrobun:

```sh
hutch run sidecar:bundle
hutch run build:canary
# or: hutch run build     # stable channel
```

`sidecar:bundle` calls the repository's `make build-bundle`, builds the current workspace wheels and installs them plus
third-party dependencies into `desktop/resources/python/`. This can download a substantial runtime and requires network
access. The generated runtime is gitignored and is separate from Electrobun's disposable `build/` and Vite's `dist/`
directories.

The release scripts check that the runtime contains `corpora_py.sidecar`. Re-run `sidecar:bundle` after Python changes,
and use these release scripts rather than calling `hutch electrobun build` directly. `build.copy` places the runtime
under `Resources/app/python`; the main process resolves it via Electrobun's `PATHS.RESOURCES_FOLDER`, never a system
Python or workspace fallback. Working files go in `Utils.paths.userData`, not the read-only app bundle, and the Hugging
Face cache defaults to a subdirectory there.

Packaged builds default to `AUTH_REQUIRED=true`: configure the existing `PROJECT_REF` / `SUPABASE_JWKS_URL` and provide
a JWT from your UI's sign-in flow before calling protected routes. `/health` and `/capabilities` remain available for
startup checks. Setting `AUTH_REQUIRED=false` explicitly also works, but loopback binding is **not** an authentication
boundary; do not ship an anonymous writable backend unintentionally.

The helper produces an **unsigned local-test** Python bundle. Configure the existing Python signing pipeline and
Electrobun signing/notarization for public distribution. Build each OS/architecture on its own runner. The current
Python bundler supports macOS arm64/x64 and Windows x64; Linux runtime packaging is not yet implemented. Heavy optional
extras such as Docling are not installed by this default bundle.

## Lifecycle and validation

`python -u -m corpora_py.sidecar --watch-parent` binds a loopback socket and announces its address; the desktop
separately health-polls with a 60-second startup deadline. Logs remain in the main-process output. A missing Python,
startup error or later crash is visible in the UI rather than silently falling back to another server. There is no
automatic restart/replay of conversion jobs.

Quitting (including closing the last window) closes Python's stdin for cross-platform graceful shutdown, then
force-kills it after five seconds if necessary. The Python launcher also watches stdin EOF when the desktop crashes or
is killed, with an eight-second last-resort exit. Quitting can interrupt active conversions; this is not a persistent
worker service.

```sh
hutch run typecheck
hutch run test          # runtime resolution + real Python lifecycle tests
# From the repository root:
uv run pytest tests/corpora_py/test_sidecar.py
```
