import { useSyncExternalStore } from "react"
import { API_URL } from "~/lib/types/socket"

/**
 * API-key settings store + auth-aware fetch wrapper.
 *
 * Two keys are managed from the Settings page (`routes/settings.tsx`):
 *
 * - Hugging Face API key -- gates the Explore features (`routes/explore.tsx`
 *   hides its browse/search UI until a key has been saved AND validated
 *   against `https://huggingface.co/api/whoami-v2`).
 * - Supabase API key -- OPTIONAL. Attached by {@link apiFetch} as an
 *   `Authorization: Bearer` header whenever one is stored, and simply omitted
 *   when it isn't. The public deployment and local dev both run the backend
 *   with `AUTH_REQUIRED=false`, so the app has to work with no key at all; a
 *   key only matters against a backend that does enforce auth.
 * - Anthropic API key -- powers the real AI agent in the corpus workspace
 *   chat (`components/workspace/use-corpus-chat.ts`), which calls the
 *   Anthropic API directly from the webview. Without a validated key the chat
 *   falls back to its mock assistant.
 *
 * Storage: `sessionStorage`, scoped to the tab/session -- keys never touch
 * localStorage, URLs, or logs. Error messages built here deliberately never
 * interpolate the key value. State is readable both from React (via
 * {@link useApiKeys}, backed by `useSyncExternalStore`) and from module-level
 * code like `uploads/manager.ts` (via plain getters), mirroring how that
 * manager already reads jotai's default store outside React.
 */

// ── Types & constants ───────────────────────────────────────────────────────

/** Build-mode switch: Bearer auth is enforced only in production builds. */
export const IS_PROD = import.meta.env.PROD

export type ApiKeyName = "hf" | "supabase" | "anthropic"

/** Validation state of a stored key ("missing" is derived from `value`). */
export type ApiKeyStatus = "unchecked" | "valid" | "invalid"

export type ApiKeyEntry = {
  value: string
  status: ApiKeyStatus
}

export type ApiKeysSnapshot = {
  hf: ApiKeyEntry
  supabase: ApiKeyEntry
  anthropic: ApiKeyEntry
}

export type ValidationResult = {
  ok: boolean
  message: string
}

const STORAGE_PREFIX = "corpora.apiKey."
const EMPTY_ENTRY: ApiKeyEntry = { value: "", status: "unchecked" }

// ── Storage plumbing ────────────────────────────────────────────────────────

const storageKey = (name: ApiKeyName): string => `${STORAGE_PREFIX}${name}`

const readEntry = (name: ApiKeyName): ApiKeyEntry => {
  if (typeof sessionStorage === "undefined") return EMPTY_ENTRY
  try {
    const raw = sessionStorage.getItem(storageKey(name))
    if (!raw) return EMPTY_ENTRY
    const parsed = JSON.parse(raw) as Partial<ApiKeyEntry>
    if (typeof parsed.value !== "string" || !parsed.value) return EMPTY_ENTRY
    const status: ApiKeyStatus =
      parsed.status === "valid" || parsed.status === "invalid"
        ? parsed.status
        : "unchecked"
    return { value: parsed.value, status }
  } catch {
    return EMPTY_ENTRY
  }
}

const listeners = new Set<() => void>()

// Cached so `useSyncExternalStore`'s getSnapshot returns a stable reference
// between writes (a fresh object every call would loop the render).
let snapshot: ApiKeysSnapshot = {
  hf: EMPTY_ENTRY,
  supabase: EMPTY_ENTRY,
  anthropic: EMPTY_ENTRY,
}
let hydrated = false

const readAll = (): ApiKeysSnapshot => ({
  hf: readEntry("hf"),
  supabase: readEntry("supabase"),
  anthropic: readEntry("anthropic"),
})

const refreshSnapshot = (): void => {
  snapshot = readAll()
  for (const listener of listeners) listener()
}

const getSnapshot = (): ApiKeysSnapshot => {
  if (!hydrated && typeof sessionStorage !== "undefined") {
    hydrated = true
    snapshot = readAll()
  }
  return snapshot
}

// SSR/prerender-safe: no sessionStorage on the server, so the server snapshot
// is the empty state and the client rehydrates on mount.
const getServerSnapshot = (): ApiKeysSnapshot => snapshot

const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// ── Public store API ────────────────────────────────────────────────────────

/** React hook: live view of both keys (value + validation status). */
export const useApiKeys = (): ApiKeysSnapshot =>
  useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

/** Non-React read (module-level code like `uploads/manager.ts`). */
export const getApiKey = (name: ApiKeyName): ApiKeyEntry => getSnapshot()[name]

export const setApiKey = (
  name: ApiKeyName,
  value: string,
  status: ApiKeyStatus = "unchecked"
): void => {
  if (typeof sessionStorage === "undefined") return
  const trimmed = value.trim()
  if (!trimmed) {
    clearApiKey(name)
    return
  }
  const entry: ApiKeyEntry = { value: trimmed, status }
  sessionStorage.setItem(storageKey(name), JSON.stringify(entry))
  refreshSnapshot()
}

export const markApiKeyStatus = (
  name: ApiKeyName,
  status: ApiKeyStatus
): void => {
  const current = getSnapshot()[name]
  if (!current.value) return
  setApiKey(name, current.value, status)
}

export const clearApiKey = (name: ApiKeyName): void => {
  if (typeof sessionStorage === "undefined") return
  sessionStorage.removeItem(storageKey(name))
  refreshSnapshot()
}

/** True once a Hugging Face key has been saved AND validated -- the gate the
 * Explore features check before rendering/fetching. */
export const hasValidHfKey = (keys: ApiKeysSnapshot = getSnapshot()): boolean =>
  keys.hf.value !== "" && keys.hf.status === "valid"

// ── Validation ──────────────────────────────────────────────────────────────

/** Verifies a Hugging Face token against the Hub's whoami endpoint. */
export const validateHfKey = async (key: string): Promise<ValidationResult> => {
  const trimmed = key.trim()
  if (!trimmed) return { ok: false, message: "Enter a key first." }
  try {
    const response = await fetch("https://huggingface.co/api/whoami-v2", {
      headers: { Authorization: `Bearer ${trimmed}` },
    })
    if (response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        name?: string
      }
      return {
        ok: true,
        message: body.name
          ? `Key verified — authenticated as ${body.name}.`
          : "Key verified.",
      }
    }
    if (response.status === 401) {
      return {
        ok: false,
        message:
          "Hugging Face rejected the key (401). Check the token in your Hub settings and try again.",
      }
    }
    return {
      ok: false,
      message: `Hugging Face validation failed (${response.status}). Try again.`,
    }
  } catch {
    return {
      ok: false,
      message:
        "Could not reach huggingface.co to validate the key. Check your connection and try again.",
    }
  }
}

// Loose JWT shape (three dot-separated base64url segments) -- catches the
// common mistake of pasting a `sb_publishable_...` / `sb_secret_...` API key
// instead of a session access token, before a network round-trip.
const JWT_SHAPE = /^[\w-]+\.[\w-]+\.[\w-]+$/

/** Whether the backend answers a protected endpoint with no credentials at
 * all -- true when it runs with `AUTH_REQUIRED=false`, in which case no key
 * is needed and none can meaningfully be validated. */
export const backendRequiresAuth = async (): Promise<boolean> => {
  const response = await fetch(`${API_URL}/storage`)
  return response.status === 401 || response.status === 403
}

/**
 * Validates a Supabase key against the corpora-api backend by probing a
 * protected endpoint with the key as a Bearer token: a 401/403 means the
 * backend rejected it; any other outcome (200, or even a 5xx from further in
 * the handler) means it made it past auth.
 *
 * Probes anonymously first: against a deployment that doesn't enforce auth,
 * *every* key "passes", so reporting success would be a lie. Say so instead.
 */
export const validateSupabaseKey = async (
  key: string
): Promise<ValidationResult> => {
  const trimmed = key.trim()
  if (!trimmed) return { ok: false, message: "Enter a key first." }
  try {
    if (!(await backendRequiresAuth())) {
      return {
        ok: true,
        message:
          "This deployment doesn't require a key — the backend accepts anonymous requests, so you can skip this.",
      }
    }
  } catch {
    return {
      ok: false,
      message:
        "Could not reach the backend to validate the key. Check that the API is running and try again.",
    }
  }
  if (!JWT_SHAPE.test(trimmed)) {
    return {
      ok: false,
      message:
        "That's not a Supabase access token. The backend verifies a signed-in user's JWT (three dot-separated segments, starts with `eyJ`) — not a `sb_publishable_…` project API key.",
    }
  }
  try {
    const response = await fetch(`${API_URL}/storage`, {
      headers: { Authorization: `Bearer ${trimmed}` },
    })
    if (response.status === 401 || response.status === 403) {
      return {
        ok: false,
        message:
          "The backend rejected the token. It must be a current, unexpired access token for this project's Supabase instance.",
      }
    }
    return { ok: true, message: "Token accepted by the backend." }
  } catch {
    return {
      ok: false,
      message:
        "Could not reach the backend to validate the key. Check that the API is running and try again.",
    }
  }
}

/**
 * Extra header Anthropic requires before it will serve a browser (CORS)
 * request at all -- the app talks to the API directly from the webview with
 * the user's own key, there is no proxy in between.
 */
export const ANTHROPIC_BROWSER_HEADERS: Record<string, string> = {
  "anthropic-dangerous-direct-browser-access": "true",
}

/**
 * Verifies an Anthropic API key by listing models -- the cheapest
 * authenticated call, and its response doubles as a sanity check that the
 * browser can reach the API cross-origin.
 */
export const validateAnthropicKey = async (
  key: string
): Promise<ValidationResult> => {
  const trimmed = key.trim()
  if (!trimmed) return { ok: false, message: "Enter a key first." }
  try {
    const response = await fetch(
      "https://api.anthropic.com/v1/models?limit=1",
      {
        headers: {
          "x-api-key": trimmed,
          "anthropic-version": "2023-06-01",
          ...ANTHROPIC_BROWSER_HEADERS,
        },
      }
    )
    if (response.ok)
      return { ok: true, message: "Key verified with Anthropic." }
    if (response.status === 401) {
      return {
        ok: false,
        message:
          "Anthropic rejected the key (401). Check it in the Anthropic console and try again.",
      }
    }
    return {
      ok: false,
      message: `Anthropic validation failed (${response.status}). Try again.`,
    }
  } catch {
    return {
      ok: false,
      message:
        "Could not reach api.anthropic.com to validate the key. Check your connection and try again.",
    }
  }
}

/** True once an Anthropic key has been saved AND validated -- the gate the
 * chat panel checks before running the real agent instead of the mock. */
export const hasValidAnthropicKey = (
  keys: ApiKeysSnapshot = getSnapshot()
): boolean => keys.anthropic.value !== "" && keys.anthropic.status === "valid"

// ── Auth-aware fetch ────────────────────────────────────────────────────────

/**
 * `window.fetch` bound to the global. The AI SDK stores its `fetch` option as
 * an object property and calls it method-style, which re-binds `this` to that
 * object — Chrome then throws "Illegal invocation". An arrow wrapper keeps the
 * call on the global no matter how it's invoked.
 */
// Cast: Bun's global types add a `preconnect` static to `typeof fetch` that a
// plain wrapper can't carry; the SDK only ever calls the function itself.
export const boundFetch = ((input: RequestInfo | URL, init?: RequestInit) =>
  globalThis.fetch(input, init)) as typeof fetch

/**
 * `Authorization` header for backend calls: the Supabase Bearer token when
 * one has been stored, nothing otherwise.
 *
 * Deliberately never throws. The public deployment runs the backend with
 * `AUTH_REQUIRED=false` (see the root CLAUDE.md's "Auth" section), so a
 * visitor with no Supabase session must be able to convert and browse; the
 * key is an *optional* upgrade for a deployment that does enforce auth, not a
 * precondition for the app to function. Whether a given call is allowed is
 * the backend's decision to make -- surfaced as a real 401 -- not something
 * this client should pre-empt.
 */
export const authHeaders = (): Record<string, string> => {
  const { value } = getApiKey("supabase")
  return value ? { Authorization: `Bearer ${value}` } : {}
}

/**
 * Drop-in `fetch` replacement for corpora-api calls: merges
 * {@link authHeaders} into the request.
 */
export const apiFetch = async (
  input: string | URL,
  init: RequestInit = {}
): Promise<Response> => {
  const headers = new Headers(init.headers)
  for (const [name, value] of Object.entries(authHeaders())) {
    headers.set(name, value)
  }
  return fetch(input, { ...init, headers })
}

/**
 * Appends the Supabase key as a `?token=` query param when one is stored --
 * browser `WebSocket` clients can't set custom headers on the handshake, so
 * the backend's `AuthMiddleware` accepts the token this way for `/ws` routes.
 * Like {@link authHeaders} this is a no-op without a key rather than an
 * error, so a tokenless deployment can still stream job status.
 */
export const withWsAuth = (wsUrl: string): string => {
  const { value } = getApiKey("supabase")
  if (!value) return wsUrl
  const separator = wsUrl.includes("?") ? "&" : "?"
  return `${wsUrl}${separator}token=${encodeURIComponent(value)}`
}
