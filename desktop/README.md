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

The shell uses **Motion Panels** for three resizable plugin panels: **sidebar** (left), **inspector** (right), and
**dock** (below the editors). Each panel contains an ordered, multi-expand accordion. Navigation and recent jobs start
in the sidebar; job details and sidecar status start in the inspector; connection events and job logs start in the dock.
Use a section's options menu to reorder, move it to another panel, or remove its placement. The panel's **+** menu adds
any removed plugin. Several sections can remain expanded together.

The central primary/secondary editor groups remain separate from plugin placement. Home is pinned in the primary
group. Explorer starts in the secondary group and remains a scaffold; no library is connected to it yet. Other views
and jobs open as globally deduplicated, closable tabs. The tab menu selects overflowed tabs or moves the active tab
between editor groups. Delete closes an unpinned tab.

- The titlebar is a native drag region; panel toggles and Settings stay clickable. Resize seams with the pointer or
  keyboard arrows (Shift for larger steps); Home/End set bounds, double-click resets the default size, and Enter folds
  or reopens a panel. Open sizes and plugin arrangement survive folding. Layout stays in memory for this session.
- **Events** in the status bar opens and expands the connection-events plugin wherever it is currently placed. Opening
  a job expands its logs plugin, and the inspector follows the focused job. Events show the latest 50 observed backend
  status changes, not an unrestricted Python console stream.
- Automatic sidecar checks run every three seconds while starting/offline, then stop when Python is ready. **Check
  sidecar** remains available while online or paused. A later crash is observed by a manual check. Settings can pause
  checks without stopping Python or conversion tracking.
- Settings cycles **system → light → dark**. Only this appearance preference persists on the device. Tokens, files,
  jobs, tabs, and panel sizes stay in memory.

### Shared renderer state and plugin contract

`src/shared/store.ts` owns the application state. `main.tsx` supplies one Jotai `Provider` store, and App owns the
backend, conversion, event, and appearance controllers above every plugin. Closing, removing, moving, or folding a
plugin never cancels a conversion or unsubscribes those controllers.

Plugin definitions register in `src/mainview/panel-plugins.tsx` through `PanelPluginRegistry` in `src/lib/panel.ts`.
Register before mounting the workspace. A definition supplies a stable ID, name, default area, and component. Its ID
never changes when moved; the area prefix on built-in IDs records their default location only. Registration is separate
from the user's ordered `{ id, area, expanded }` placements in `pluginPlacementsAtom`.

Dispatch `panelActionAtom` with these actions:

| Action | Behavior |
| --- | --- |
| `set-open { area, open }` / `toggle { area }` | Open or fold the whole panel while retaining its size and placement state. |
| `add { id, area?, index? }` | Add a registered plugin, expanded, and reveal its panel. An existing placement is unchanged. |
| `open { id, area?, index? }` / `close { id }` | Open expands the existing placement and reveals its panel; a removed plugin is re-added at the specified or default area. Close folds the section but retains its header and position. |
| `move { id, area, index? }` | Move an existing placement, retaining ID and expansion, and reveal the destination. `index` is zero-based within that panel; omitted appends, out-of-range values clamp. |
| `remove { id }` / `set-expanded { area, ids }` | Remove only the placement, or set that panel's independently expanded sections. Unknown/unplaced IDs cannot create phantom sections. |

Removing a plugin preserves its keyed domain state. Re-adding uses its default location unless an area is supplied;
its former position is intentionally discarded. Moves across React parents can remount the view: retain application
state in Jotai keyed by stable plugin ID, not current area. The logs plugin uses its stable ID and job ID for its search
and level filters, independently of detail-view filters. Arbitrary React local state and DOM scroll/focus are not
promised to survive a move.

Drafts and selected files survive tab closes, moves, and panel folds. Removing/replacing a file, clearing the form, or
successful submission releases retained previews. Token/endpoint changes reset conversion state and remove all
identity-bound job tabs. **Reset panel layout** in the Corpora menu restores the default tabs, sizes, and plugin
placements without discarding a draft or stopping jobs.

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
