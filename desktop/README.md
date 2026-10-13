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
sidecar status, the loopback endpoint, auth policy and RPC response time. Jobs submits real conversions to the managed
Python API and tracks them across tab switches. Explorer remains a scaffold; library browsing is not wired up yet.

- The 52-point titlebar is a native drag region. On macOS, hidden-inset window controls use a 16-point left / 19-point
  top inset to center their 14-point native buttons. Theme buttons remain clickable.
- The appearance button cycles **system → light → dark**. Preferences are stored in webview local storage; system mode
  follows OS appearance changes. Settings exposes the same control.
- The bottom status bar stays visible while content scrolls. **Events** expands the latest 50 observed backend state
  changes in this session; it is not a Python console-log stream. Repeated identical poll responses are not logged.
- Automatic sidecar checks run every three seconds only while starting/offline, and stop as soon as Python is ready.
  Background retries do not animate the check button. **Check sidecar** still works while online or paused; observing an
  offline state rearms enabled automatic checks. Because online polling stops, a later sidecar crash is observed by a
  manual check, not a continuous health probe.
- Settings can pause/resume automatic status checks without stopping Python or job tracking. RPC timing is reported only
  for successful responses, not failed connection attempts.

### Conversion jobs

The Jobs workspace uses the ReUI file-type, attachment, icon-stack and review/progress stepper patterns. Choose a source
(EPUB, HTML, XML/TEI, PDF, text/Markdown, Text-Fabric ZIP or TEI ZIP), review its name, description, category and
`.corpus` / `.cusx` / `.ctei` output, then submit. Dataset ZIP inputs require an explicit type and only support
`.corpus`. The desktop and backend accept nonempty uploads up to **500 MiB**; source validation can still reject invalid
contents.

Python's executor runs the conversion in the background. The app-level controller polls active jobs every 1.5 seconds,
without a loading flash for unchanged snapshots, and stops polling when all jobs are terminal. Changing tabs does not
cancel jobs. The initial/manual list refresh loads all pages, including older active jobs; `/ingest` jobs are excluded.
Transient tracking failures retry without resubmitting accepted uploads. Expired jobs (404) are removed from tracking;
authentication failures stop retries until a manual refresh or token change. Upload timeout errors warn you to refresh
before submitting again because server acceptance can be ambiguous.

The detail view shows actual `metadata → convert → package → validate` stage states (the separate packaging stage is
skipped for CTEI/CUSX), not fabricated percentages. Job-scoped events carry debug/info/warning/error levels and UTC
copyable timestamps; filter by stage, level or text. The backend retains the latest 200 events with increasing sequence
numbers. Legacy string logs remain readable, without guessed levels or timestamps. This is checkpoint telemetry, not an
unrestricted Python stdout stream. Results download through authenticated HTTP after success and `download_ready`.

If auth is enabled, apply a Supabase JWT in **Settings → Backend access**. Tokens stay in memory, are never logged or
saved, and are sent only to the managed sidecar. Switching token or sidecar endpoint aborts old requests and isolates
the visible job list. The desktop does not sign in for you or bypass backend auth. Downloads use temporary blob URLs.
Quitting the desktop stops Python and may interrupt conversions; the default in-memory job registry does not survive
sidecar restarts. Rebuild the packaged Python runtime after backend telemetry changes.

Run `make desktop-typecheck` and `make desktop-test` from the repository root, or `bun test src/lib src/components` from
`desktop/` for controller and UI rendering regressions.

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
startup error is visible in the UI rather than silently falling back to another server; after readiness, use **Check
sidecar** to observe a later crash. There is no automatic restart/replay of conversion jobs.

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
