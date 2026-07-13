import { getDefaultStore } from "jotai"
import { API_URL } from "~/lib/types/socket"
import { uploadAtom, type UploadEntry } from "~/lib/atoms/upload-atom"
import {
  type JobStatusMessage,
  subscribeJobStatus
} from "~/lib/hooks/use-socket"
import { loadPersistedUploads, savePersistedUploads } from "./persistence"
import { detectSourceFormat } from "./source-format"
import { saveCorpusFile } from "./save-corpus-file"

/**
 * Module-level upload/conversion job manager.
 *
 * Everything here is deliberately OUTSIDE React: job tracking, blob caching,
 * WebSocket subscriptions, and localStorage persistence are app-singletons,
 * not per-component state. Keeping them at module level (writing to
 * `uploadAtom` through jotai's default store) means:
 *
 * - every exported function is referentially stable by construction -- no
 *   `useCallback` chains, no ref-mirror of the latest atom value;
 * - any number of components can mount `useUpload()` without duplicating
 *   hydration or WebSocket subscriptions;
 * - an in-flight job keeps being tracked even if the component that started
 *   it unmounts.
 *
 * NOTE: this reads/writes the *default* jotai store. If the app ever wraps a
 * custom `<Provider store={...}>`, this manager must be handed that store.
 */
const store = getDefaultStore()

// Coarse client-side stage markers. The server has no progress hook (see
// JobStatus's docstring in use-socket.ts) so these are NOT real completion
// percentages -- the file card renders an indeterminate animation while
// "converting" rather than trusting these numbers as progress.
const PROGRESS = { started: 0, queued: 20, converting: 60, done: 100 } as const

// The real `File` objects (needed to retry) never go into the atom -- atoms
// hold serializable UI state.
const files = new Map<string, File>()

// Per-job WebSocket unsubscribers, so the status socket can be closed early
// if the upload is deleted before the job reaches a terminal state.
const unsubscribers = new Map<string, () => void>()

// The downloaded `.corpus` bytes, cached once the server-side conversion
// succeeds and the download completes. Kept out of the atom (blobs aren't
// serializable) so `saveUpload` can retry just the local save-to-disk step
// -- which can fail independently of the conversion (e.g. the save dialog
// is dismissed with an error, or write permission is denied) -- without
// re-uploading and re-converting the whole file.
const blobs = new Map<string, { blob: Blob; filename: string }>()

const createId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`

/** Mutates one entry in the atom, no-op if it was deleted meanwhile. */
const updateEntry = (
  id: string,
  mutate: (entry: UploadEntry) => void
): void => {
  store.set(uploadAtom, (draft) => {
    const entry = draft[id]
    if (entry) mutate(entry)
  })
}

const fetchCorpusBlob = async (jobId: string): Promise<Blob> => {
  const response = await fetch(`${API_URL}/convert/${jobId}/download`)
  if (!response.ok) throw new Error(`Download failed (${response.status})`)
  return response.blob()
}

// Closes the status socket only -- the original `File` stays cached so a
// failed job can be retried (`retryUpload`) without re-picking the file.
// `deleteUpload` and the success path drop it explicitly.
const stopTracking = (id: string): void => {
  unsubscribers.get(id)?.()
  unsubscribers.delete(id)
}

const handleJobSucceeded = async (
  id: string,
  jobId: string,
  jobName: string
): Promise<void> => {
  try {
    const blob = await fetchCorpusBlob(jobId)
    // `jobName` is the server-side job name (the `name` form field sent at
    // POST /convert time), which may differ from the local file name.
    const filename = `${jobName}.corpus`

    // The conversion succeeded and the bytes are in hand -- from here, only
    // the local save-to-disk step can still fail, and that must never
    // downgrade this to "error" (see `saveUpload`).
    blobs.set(id, { blob, filename })
    // Conversion is done -- nothing left to retry from the source file, so
    // release it rather than hold large uploads in memory.
    files.delete(id)
    updateEntry(id, (draft) => {
      draft.status = "ready"
      draft.progress = PROGRESS.done
      draft.corpusName = filename
      draft.corpusSize = blob.size
    })
  } catch (error) {
    // Only a genuine server-side/network failure to fetch the
    // already-converted archive lands here -- there's nothing cached to
    // retry locally, so "Try again" re-running the whole upload is the
    // correct recovery.
    updateEntry(id, (draft) => {
      draft.status = "error"
      draft.error = error instanceof Error ? error.message : String(error)
    })
  } finally {
    stopTracking(id)
  }
}

const trackJob = (id: string, jobId: string, wsPath: string): void => {
  const wsUrl = `${API_URL.replace(/^http/, "ws")}${wsPath}`

  const handleMessage = (message: JobStatusMessage) => {
    // Applies regardless of which branch below fires -- the server can push
    // an update with the same `status` but a new `last_log` line (see
    // websocket.py), and the UI should reflect that either way.
    updateEntry(id, (draft) => {
      draft.logs = message.logs
      draft.lastLog = message.last_log
    })

    switch (message.status) {
      case "running":
        updateEntry(id, (draft) => {
          draft.status = "converting"
          draft.progress = PROGRESS.converting
        })
        break
      case "failed":
        updateEntry(id, (draft) => {
          draft.status = "error"
          draft.error = message.error ?? "Conversion failed"
        })
        stopTracking(id)
        break
      case "succeeded":
        void handleJobSucceeded(id, jobId, message.name)
        break
    }
  }

  unsubscribers.set(id, subscribeJobStatus(wsUrl, handleMessage))
}

export type UploadOptions = {
  name?: string
  description?: string
  sourceFormat?: string
}

type ConvertResponse = { job_id: string; status_url: string; ws_url: string }

/**
 * Uploads a file to the `corpora-api` conversion endpoint (`POST /convert`,
 * see `admin/services/api.py`) and tracks the job through to "ready" (the
 * `.corpus` bytes downloaded and cached). Saving to disk is a separate,
 * explicit step -- `saveUpload` -- so a pile of finished conversions never
 * fires save-as dialogs unprompted.
 *
 * `corpora-api` requires a Supabase JWT by default (`AUTH_REQUIRED=true`,
 * see the root CLAUDE.md's "Auth" section) -- this example has no Supabase
 * session to attach one from yet, so run the server locally with
 * `AUTH_REQUIRED=false` (see README.md) until real auth is wired in here.
 *
 * Multiple files can be in flight at once -- each gets its own entry in
 * `uploadAtom`, keyed by a client-generated id, and its own
 * `/convert/{job_id}/ws` subscription (`use-socket.ts`) tracking that job's
 * status through to completion.
 */
export const uploadFile = async (
  file: File,
  options: UploadOptions = {}
): Promise<string> => {
  const id = createId()
  files.set(id, file)

  store.set(uploadAtom, (draft) => {
    draft[id] = {
      id,
      name: file.name,
      size: file.size,
      type: file.type,
      status: "uploading",
      progress: PROGRESS.started,
      error: null,
      lastModified: file.lastModified || undefined,
      uploadedAt: Date.now(),
      logs: []
    }
  })

  try {
    const sourceFormat = options.sourceFormat ?? detectSourceFormat(file.name)
    updateEntry(id, (draft) => {
      draft.sourceFormat = sourceFormat
    })

    const formData = new FormData()
    formData.append("file", file)
    formData.append("source_format", sourceFormat)
    formData.append(
      "name",
      options.name?.trim() || file.name.replace(/\.[^./]+$/, "")
    )
    formData.append("description", options.description?.trim() || "")

    const response = await fetch(`${API_URL}/convert`, {
      method: "POST",
      body: formData
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string
      }
      throw new Error(body.detail ?? `Upload failed (${response.status})`)
    }

    const { job_id: jobId, ws_url: wsPath } =
      (await response.json()) as ConvertResponse

    updateEntry(id, (draft) => {
      draft.status = "queued"
      draft.progress = PROGRESS.queued
      // Persisted so a reload can resume tracking (still in flight) or
      // re-check/re-download (already "ready") this job -- see
      // `initUploadManager`.
      draft.jobId = jobId
      draft.wsPath = wsPath
    })

    trackJob(id, jobId, wsPath)
  } catch (error) {
    updateEntry(id, (draft) => {
      draft.status = "error"
      draft.error = error instanceof Error ? error.message : String(error)
    })
  }

  return id
}

export const deleteUpload = (id: string): void => {
  stopTracking(id)
  files.delete(id)
  blobs.delete(id)
  store.set(uploadAtom, (draft) => {
    delete draft[id]
  })
}

export const retryUpload = (id: string): Promise<string> | undefined => {
  const file = files.get(id)
  deleteUpload(id)
  // Retrying mints a fresh id via uploadFile() rather than reusing `id` --
  // a stale in-flight status push for the old id (unlikely but possible)
  // would otherwise resurrect a deleted atom entry. The new id is returned
  // so a view tracking the old entry can follow the retried one.
  return file ? uploadFile(file) : undefined
}

/**
 * Saves (or retries saving) the converted `.corpus` bytes to disk for an
 * entry in "ready" -- kept separate from `retryUpload`, which re-runs the
 * whole upload+conversion and can't fix a save-dialog failure.
 */
export const saveUpload = async (id: string): Promise<void> => {
  let cached = blobs.get(id)

  if (!cached) {
    // Nothing cached in this process -- either the page was reloaded since
    // the conversion succeeded (blobs don't survive that, unlike the
    // persisted atom entry) or this is a retry after a previous save
    // already cleared the cache. Re-fetch using the job id, which *is*
    // persisted -- the `.corpus` file survives in `_RESULTS_ROOT` on the
    // server independent of this client's lifetime.
    const entry = store.get(uploadAtom)[id]
    if (!entry?.jobId || !entry.corpusName) return
    try {
      const blob = await fetchCorpusBlob(entry.jobId)
      cached = { blob, filename: entry.corpusName }
      blobs.set(id, cached)
    } catch (error) {
      console.error("Failed to re-download converted corpus file:", error)
      return
    }
  }

  try {
    await saveCorpusFile(cached.filename, cached.blob)
    updateEntry(id, (draft) => {
      draft.status = "success"
    })
    blobs.delete(id)
  } catch (error) {
    // The conversion already succeeded and the bytes are safely cached in
    // `blobs` -- only the local save step failed. Log for diagnosis but
    // deliberately don't set `status: "error"` here: that would point the
    // UI at "Try again", which re-runs the entire upload+conversion and
    // can't fix a save-dialog failure. Leaving `status: "ready"` keeps the
    // "Save" action available so the user can retry just this step.
    console.error("Failed to save converted corpus file:", error)
  }
}

// Confirms a rehydrated "ready" entry (server said "succeeded" in a past
// session) is still actually downloadable before leaving it in the list.
// Deliberately does NOT auto-fetch the blob or pop the save dialog here --
// only `GET /convert/{id}` (a cheap status check), not `/download` -- so
// reopening the app after several past conversions doesn't fire off a pile
// of save-as dialogs unprompted. `saveUpload` fetches the bytes on-demand
// once the user actually clicks "Save file".
const reconcileReady = async (id: string, jobId: string): Promise<void> => {
  try {
    const response = await fetch(`${API_URL}/convert/${jobId}`)
    if (!response.ok) throw new Error(`Job lookup failed (${response.status})`)
    const status = (await response.json()) as {
      status: string
      download_ready: boolean
    }
    if (status.status !== "succeeded" || !status.download_ready) {
      throw new Error(`Job is ${status.status}, not ready`)
    }
  } catch {
    // The server restarted (its in-memory `JobManager` forgot this job --
    // see jobs.py) or the result was otherwise reaped. There's nothing left
    // to save, so drop this history entry rather than leave a permanently
    // broken "Save" button behind.
    store.set(uploadAtom, (draft) => {
      delete draft[id]
    })
  }
}

let initialized = false

/**
 * One-time, idempotent startup: rehydrates past-conversion history from
 * localStorage into the atom, resumes tracking for jobs still in flight,
 * reconciles "ready" entries against the server, and only THEN starts
 * mirroring atom changes back to localStorage.
 *
 * Ordering matters: subscribing to the atom only after hydration means the
 * initial empty atom can never overwrite the persisted history (which a
 * naive "persist on every change" effect would do on first render).
 *
 * Called from `useUpload`'s mount effect (so it never runs during SSR/
 * prerender, where there's no `localStorage`), but safe to call any number
 * of times from any number of components.
 */
export const initUploadManager = (): void => {
  if (initialized || typeof window === "undefined") return
  initialized = true

  const persisted = loadPersistedUploads()

  store.set(uploadAtom, (draft) => {
    for (const entry of persisted) draft[entry.id] = entry
  })

  for (const entry of persisted) {
    if (!entry.jobId) continue
    if (entry.status === "queued" || entry.status === "converting") {
      // Still in flight as of the last session -- resume live tracking.
      // `websocket.py` sends the job's current status as soon as this
      // connects, so this also self-corrects if it actually finished (or
      // failed, or the server restarted and 404s) while the app was closed.
      if (entry.wsPath) trackJob(entry.id, entry.jobId, entry.wsPath)
    } else if (entry.status === "ready") {
      void reconcileReady(entry.id, entry.jobId)
    }
  }

  // Mirror every subsequent change so history survives a reload/relaunch --
  // see `savePersistedUploads` for what's deliberately excluded (and
  // `persistence.ts` for why this doesn't try to survive a *server*
  // restart). Never unsubscribed: this manager lives for the whole app.
  store.sub(uploadAtom, () => {
    savePersistedUploads(store.get(uploadAtom))
  })
}
