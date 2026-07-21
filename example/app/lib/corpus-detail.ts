import { apiFetch } from "~/lib/settings"
import { API_URL } from "~/lib/types/socket"

/**
 * Typed API client + pure helpers for the corpus-detail feature.
 *
 * Backend contract (base URL = {@link API_URL}):
 * - GET   /storage/{filename}/manifest
 * - PATCH /storage/{filename}/manifest
 * - GET   /storage/{filename}/index
 * - GET   /storage/{filename}/content?ref=&fmt=&offset=&limit=
 *
 * where `{filename}` is the full archive filename INCLUDING `.corpus`,
 * URL-encoded. Route `:id` = filename WITHOUT `.corpus`. The pure helpers
 * below convert between the two and hold no reference to `API_URL` so they
 * stay trivially unit-testable; the async fetchers own the `encodeURIComponent`
 * + network work.
 *
 * Error convention: every async fetcher resolves with parsed JSON on a 2xx
 * response, and rejects with an `Error` whose message is the backend's
 * `{detail}` string (falling back to `Request failed (<status>)`) on any
 * non-2xx — mirroring how `explore.tsx` surfaces `body.detail` in an Alert.
 */

// ── Response types ──────────────────────────────────────────────────────────

/** `GET /storage/{filename}/manifest` — unknown extra keys are preserved. */
export type Manifest = {
  uid?: string
  name?: string
  description?: string
  version?: string
  language?: string
  languageCode?: string
  type?: string
  format?: string
  format_version?: string
  category?: string
  written_date?: string
  tocFile?: string
  datasetId?: string
  projectId?: string
  assets?: unknown
  thumbnail?: string
  [key: string]: unknown
}

/** The editable subset accepted by `PATCH /storage/{filename}/manifest`. */
export type ManifestPatch = {
  name?: string
  description?: string
  version?: string
  language?: string
  languageCode?: string
  type?: string
  category?: string
  written_date?: string
}

/** The manifest keys the detail UI exposes for editing, in display order. */
export const EDITABLE_MANIFEST_FIELDS = [
  "name",
  "description",
  "version",
  "language",
  "languageCode",
  "type",
  "category",
  "written_date",
] as const satisfies readonly (keyof ManifestPatch)[]

export type EditableManifestField = (typeof EDITABLE_MANIFEST_FIELDS)[number]

/** A leaf under a top-level index item (e.g. a chapter or page). */
export type IndexChild = {
  title: string
  ref: string
}

/** A top-level index item (e.g. a book or section) with its children. */
export type IndexItem = {
  title: string
  ref: string
  children: IndexChild[]
}

export type IndexSections = {
  levels: string[]
  items: IndexItem[]
}

export type NodeType = {
  type: string
  count: number
}

/** `GET /storage/{filename}/index`. */
export type CorpusIndex = {
  toc: Record<string, unknown> | null
  sections: IndexSections | null
  node_types: NodeType[]
}

/** A single passage in a content response. */
export type Passage = {
  ref: string
  text: string
}

/** `GET /storage/{filename}/content`. */
export type ContentResponse = {
  ref: string | null
  format: string
  passages: Passage[]
  total: number
  offset: number
  limit: number
  next_offset: number | null
}

/** Options for {@link fetchContent} — mirrors the content query params. */
export type ContentQuery = {
  ref?: string | null
  fmt?: string | null
  offset?: number
  limit?: number
}

// ── Pure helpers (no API_URL / fetch — safe to unit-test in isolation) ───────

/**
 * Route `:id` → full archive filename. `:id` is the filename with the trailing
 * `.corpus` stripped, so the client simply re-appends it (per the route/id
 * contract: "the client appends '.corpus' to build API paths").
 */
export const idToFilename = (id: string): string => `${id}.corpus`

/**
 * Full archive filename → route `:id` (strip a trailing `.corpus`). Uses the
 * same anchored, case-insensitive regex as `explore.tsx`'s `displayName` so
 * the two representations can't drift apart.
 */
export const filenameToId = (filename: string): string =>
  filename.replace(/\.corpus$/i, "")

/** A flattened section-index entry for the viewer's section picker. */
export type PickerOption = {
  ref: string
  label: string
}

/**
 * Flatten an index's `sections` into an ordered list of picker options:
 * every top-level item followed by its children, children indented two spaces
 * so the hierarchy reads in a plain `<select>`. Returns `[]` when there are no
 * sections (the picker is then hidden).
 */
export const pickerOptions = (
  sections: IndexSections | null
): PickerOption[] => {
  if (!sections) return []
  const options: PickerOption[] = []
  for (const item of sections.items) {
    options.push({ ref: item.ref, label: item.title })
    for (const child of item.children) {
      options.push({ ref: child.ref, label: `  ${child.title}` })
    }
  }
  return options
}

// ── Internal fetch plumbing ─────────────────────────────────────────────────

/** Base path for a corpus's storage endpoints, with the filename encoded. */
const storagePath = (id: string): string =>
  `${API_URL}/storage/${encodeURIComponent(idToFilename(id))}`

/**
 * Parse a `fetch` Response: return JSON on 2xx, otherwise throw an `Error`
 * carrying the backend's `{detail}` message (or a generic status fallback).
 */
const parseJson = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string
    }
    throw new Error(body.detail ?? `Request failed (${response.status})`)
  }
  return (await response.json()) as T
}

// ── Async API client ────────────────────────────────────────────────────────

export const fetchManifest = async (id: string): Promise<Manifest> => {
  const response = await apiFetch(`${storagePath(id)}/manifest`)
  return parseJson<Manifest>(response)
}

export const patchManifest = async (
  id: string,
  patch: ManifestPatch
): Promise<Manifest> => {
  const response = await apiFetch(`${storagePath(id)}/manifest`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  })
  return parseJson<Manifest>(response)
}

export const fetchIndex = async (id: string): Promise<CorpusIndex> => {
  const response = await apiFetch(`${storagePath(id)}/index`)
  return parseJson<CorpusIndex>(response)
}

export const fetchContent = async (
  id: string,
  query: ContentQuery = {}
): Promise<ContentResponse> => {
  const params = new URLSearchParams()
  if (query.ref != null && query.ref !== "") params.set("ref", query.ref)
  if (query.fmt != null && query.fmt !== "") params.set("fmt", query.fmt)
  if (query.offset != null) params.set("offset", String(query.offset))
  if (query.limit != null) params.set("limit", String(query.limit))
  const suffix = params.toString() ? `?${params.toString()}` : ""
  const response = await apiFetch(`${storagePath(id)}/content${suffix}`)
  return parseJson<ContentResponse>(response)
}

/** Human-friendly label for an editable manifest field. */
export const manifestFieldLabel = (field: EditableManifestField): string => {
  switch (field) {
    case "name":
      return "Name"
    case "description":
      return "Description"
    case "version":
      return "Version"
    case "language":
      return "Language"
    case "languageCode":
      return "Language code"
    case "type":
      return "Type"
    case "category":
      return "Category"
    case "written_date":
      return "Written date"
  }
}

/**
 * Build a `ManifestPatch` from an edit-form draft, keeping only the editable
 * keys and dropping values unchanged from the original manifest so the PATCH
 * body stays minimal. Empty strings are sent through (they clear a field).
 */
export const buildManifestPatch = (
  original: Manifest,
  draft: Record<EditableManifestField, string>
): ManifestPatch => {
  const patch: ManifestPatch = {}
  for (const field of EDITABLE_MANIFEST_FIELDS) {
    const next = draft[field] ?? ""
    const prev = original[field] == null ? "" : String(original[field])
    if (next !== prev) patch[field] = next
  }
  return patch
}
