import type { UploadEntry } from "~/lib/atoms/upload-atom"

// Where past-conversion history is mirrored so it survives a page reload or
// app relaunch. `corpora-api`'s `JobManager` (see jobs.py) is in-memory only
// -- this is deliberately NOT trying to survive a server restart too; if the
// server process restarts, `GET /convert/{id}` 404s for every job it used to
// know about (even though the finished `.corpus` file is often still on
// disk), and the reconcile pass in the upload manager drops those entries
// rather than pretend they're recoverable.
const STORAGE_KEY = "corpora:uploads"

export const loadPersistedUploads = (): UploadEntry[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as UploadEntry[]) : []
  } catch {
    return []
  }
}

export const savePersistedUploads = (
  uploads: Record<string, UploadEntry>
): void => {
  // Only entries with a `jobId` are resumable/re-checkable against the
  // server -- "uploading" hasn't gotten one yet, and a page reload mid
  // upload can't resume a `fetch()` body anyway, so there's nothing useful
  // to persist for it.
  const persistable = Object.values(uploads).filter((entry) => entry.jobId)
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persistable))
  } catch {
    // Storage full or unavailable (e.g. private browsing) -- history just
    // won't survive a reload; the feature degrades, it doesn't break.
  }
}
