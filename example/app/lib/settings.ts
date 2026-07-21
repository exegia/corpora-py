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
 * - Supabase API key -- attached by {@link apiFetch} as an
 *   `Authorization: Bearer` header on every corpora-api call, but ONLY in a
 *   production build ({@link IS_PROD}). In development the backend runs with
 *   `AUTH_REQUIRED=false`, so the header is omitted and the key is optional.
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

// Loose JWT shape (three dot-separated base64url segments) -- catches typos
// and pasted anon-key fragments before a network round-trip.
const JWT_SHAPE = /^[\w-]+\.[\w-]+\.[\w-]+$/

/**
 * Validates a Supabase key against the corpora-api backend by probing a
 * protected endpoint with the key as a Bearer token: a 401/403 means the
 * backend rejected it; any other outcome (200, or even a 5xx from further in
 * the handler) means it made it past auth.
 */
export const validateSupabaseKey = async (
  key: string
): Promise<ValidationResult> => {
  const trimmed = key.trim()
  if (!trimmed) return { ok: false, message: "Enter a key first." }
  if (!JWT_SHAPE.test(trimmed)) {
    return {
      ok: false,
      message:
        "That doesn't look like a Supabase JWT (expected three dot-separated segments). Copy it from the Supabase dashboard.",
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
          "The backend rejected the key. Make sure it's a current key from the Supabase dashboard.",
      }
    }
    return { ok: true, message: "Key accepted by the backend." }
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

/** Thrown by {@link apiFetch} in production when no Supabase key is stored --
 * call sites surface `error.message` through their existing error paths. */
export class MissingApiKeyError extends Error {
  constructor() {
    super(
      "Supabase API key required. Add it in Settings to call the backend in production."
    )
    this.name = "MissingApiKeyError"
  }
}

/** `Authorization` header for backend calls: the Supabase Bearer token in
 * production, nothing in development (backend auth is bypassed there). */
export const authHeaders = (): Record<string, string> => {
  if (!IS_PROD) return {}
  const { value } = getApiKey("supabase")
  if (!value) throw new MissingApiKeyError()
  return { Authorization: `Bearer ${value}` }
}

/**
 * Drop-in `fetch` replacement for corpora-api calls: merges
 * {@link authHeaders} into the request. In production with no stored key it
 * rejects with {@link MissingApiKeyError} instead of firing a doomed 401.
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
 * Appends the Supabase key as a `?token=` query param in production --
 * browser `WebSocket` clients can't set custom headers on the handshake, so
 * the backend's `AuthMiddleware` accepts the token this way for `/ws` routes.
 */
export const withWsAuth = (wsUrl: string): string => {
  if (!IS_PROD) return wsUrl
  const { value } = getApiKey("supabase")
  if (!value) throw new MissingApiKeyError()
  const separator = wsUrl.includes("?") ? "&" : "?"
  return `${wsUrl}${separator}token=${encodeURIComponent(value)}`
}
