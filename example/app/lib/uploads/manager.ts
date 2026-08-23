import { getDefaultStore } from "jotai"
import { apiFetch, withWsAuth } from "~/lib/settings"
import { API_URL } from "~/lib/types/socket"
import {
  uploadAtom,
  type StorageOutcome,
  type UploadEntry,
  type ValidationOutcome,
} from "~/lib/atoms/upload-atom"
import {
  type JobStatusMessage,
  pollJobStatus,
  subscribeJobStatus,
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
const PROGRESS = {
  started: 0,
  queued: 20,
  converting: 60,
  validating: 85,
  done: 100,
} as const

// The real `File` objects (needed to retry) never go into the atom -- atoms
// hold serializable UI state. The upload options ride along so a retry
// re-runs with the same detected source format and inspection notes.
const files = new Map<string, { file: File; options: UploadOptions }>()

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
  const response = await apiFetch(`${API_URL}/convert/${jobId}/download`)
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

/**
 * Runs the converted archive through `POST /validate` (by job id -- see
 * `admin.services.validation_api`), mapping every outcome to a
 * `ValidationOutcome` instead of throwing: an unreachable/failing validation
 * *request* is "skipped" (the check couldn't run), while a 200 with
 * `valid: false` is "invalid" (the check ran and the corpus is broken).
 * Neither blocks the download -- see `handleJobSucceeded`.
 */
const validateConversion = async (
  jobId: string
): Promise<ValidationOutcome> => {
  try {
    const response = await apiFetch(`${API_URL}/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string
      }
      throw new Error(
        body.detail ?? `Validation request failed (${response.status})`
      )
    }
    const result = (await response.json()) as {
      valid: boolean
      reasons: string[]
      stats: Record<string, number> | null
    }
    return result.valid
      ? { status: "valid", stats: result.stats ?? undefined }
      : { status: "invalid", reasons: result.reasons }
  } catch (error) {
    return {
      status: "skipped",
      reasons: [error instanceof Error ? error.message : String(error)],
    }
  }
}

/**
 * Publishes the converted archive to the Hugging Face Hub storage repo
 * (`POST /storage` by job id -- see `admin.services.storage_api`), mapping
 * every outcome to a `StorageOutcome` instead of throwing. A 201 is
 * "stored" (with the archive's `resolve/main` download URL); anything else
 * -- storage not configured on the server (503), the Hub rejecting the
 * upload (502), a network error -- is "skipped" with the reason, and can
 * simply be retried. App code goes through `publishUpload`, which tracks
 * the outcome on the entry; this is exported for unit tests.
 */
export const publishConversion = async (
  jobId: string
): Promise<StorageOutcome> => {
  try {
    const response = await apiFetch(`${API_URL}/storage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId }),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string
      }
      throw new Error(
        body.detail ?? `Publish request failed (${response.status})`
      )
    }
    const stored = (await response.json()) as {
      filename: string
      size_bytes: number | null
      repo_id: string
      url: string
    }
    return {
      status: "stored",
      url: stored.url,
      repoId: stored.repo_id,
      filename: stored.filename,
      sizeBytes: stored.size_bytes ?? undefined,
    }
  } catch (error) {
    return {
      status: "skipped",
      reasons: [error instanceof Error ? error.message : String(error)],
    }
  }
}

const handleJobSucceeded = async (
  id: string,
  jobId: string,
  jobName: string,
  resultFilename: string
): Promise<void> => {
  // Validate before downloading: the verdict annotates the conversion (the
  // "Dataset validated" stage in the console) but never gates it -- an
  // invalid or unvalidatable archive is still downloaded and saveable, with
  // the problem surfaced in the UI instead of silently discarding minutes of
  // conversion work.
  updateEntry(id, (draft) => {
    draft.status = "validating"
    draft.progress = PROGRESS.validating
    draft.validation = { status: "running" }
  })
  const validation = await validateConversion(jobId)
  updateEntry(id, (draft) => {
    draft.validation = validation
  })

  // Publishing to the Hugging Face Hub deliberately does NOT happen here:
  // it's a manual step (`publishUpload`) the user triggers from the result
  // panel once the conversion is done, so nothing leaves this machine for
  // the Hub without an explicit click.

  try {
    const blob = await fetchCorpusBlob(jobId)
    // The server is the source of truth for the result filename: it
    // derives a slug from the user-supplied `name` and always ends in
    // `.corpus` (see issue #108). Using the server-supplied value means a
    // reload-then-re-download (which goes through `saveUpload`'s
    // `entry.corpusName` path) keeps the same filename, and the library
    // never persists the original source filename as the corpus name.
    // `jobName` is kept only as a defensive fallback for older servers
    // that don't send `result_filename` yet.
    const filename = resultFilename ?? `${jobName}.corpus`

    // The conversion succeeded, and the bytes are in hand -- from here, only
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
  // WebSocket handshakes can't carry an Authorization header, so in
  // production the Supabase key rides along as a `?token=` query param
  // (matching the backend's AuthMiddleware WebSocket contract).
  const wsUrl = withWsAuth(`${API_URL.replace(/^http/, "ws")}${wsPath}`)

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
        void handleJobSucceeded(
          id,
          jobId,
          message.name,
          message.result_filename
        )
        break
    }
  }

  // The WebSocket is the preferred transport (real push, no polling
  // traffic) and is what the desktop sidecar serves. On the Vercel
  // deployment it is unreliable in a sneaky way: the handshake succeeds and
  // the current status is pushed, but a long conversion then sits idle for
  // minutes (the server only pushes on status change, and sends no pings),
  // so the proxy/function duration limit kills the socket MID-JOB. Any
  // close or error before a terminal status therefore falls back to
  // polling -- which on Vercel also keeps a request in flight, without
  // which the frozen function instance stops advancing the conversion
  // thread at all. Only a close after "succeeded"/"failed" (the server
  // closing a finished stream, mirrored by subscribeJobStatus) means
  // tracking is genuinely done.
  let settled = false
  let fallback: (() => void) | undefined

  const startPolling = () => {
    if (fallback || settled) return
    fallback = pollJobStatus(async () => {
      const response = await apiFetch(`${API_URL}/convert/${jobId}`)
      if (!response.ok) throw new Error(`Status check failed (${response.status})`)
      return (await response.json()) as JobStatusMessage
    }, handleMessage)
  }

  const closeSocket = subscribeJobStatus(
    wsUrl,
    (message) => {
      if (message.status === "succeeded" || message.status === "failed") {
        settled = true
      }
      handleMessage(message)
    },
    (status) => {
      if (status === "error" || status === "closed") startPolling()
    }
  )

  unsubscribers.set(id, () => {
    closeSocket()
    fallback?.()
  })
}

export type UploadOptions = {
  name?: string
  description?: string
  sourceFormat?: string
  /** Pre-upload inspection notes to surface in the conversion console. */
  inspection?: string[]
}

type ConvertResponse = { job_id: string; status_url: string; ws_url: string }

/**
 * Uploads a file to the `corpora-api` conversion endpoint (`POST /convert`,
 * see `admin/services/api.py`) and tracks the job through to "ready" (the
 * `.corpus` bytes downloaded and cached). Saving to disk is a separate,
 * explicit step -- `saveUpload` -- so a pile of finished conversions never
 * fires save-as dialogs unprompted.
 *
 * `corpora-api` gates every route behind a Supabase JWT *by default*
 * (`AUTH_REQUIRED=true`, see the root CLAUDE.md's "Auth" section), and this
 * example has no Supabase session to mint one from. Both the public
 * deployment and local dev therefore run the backend with
 * `AUTH_REQUIRED=false` (see README.md); `apiFetch` attaches a Bearer token
 * only if one happens to be stored in Settings, so nothing here breaks either
 * way.
 *
 * Multiple files can be in flight at once -- each gets its own entry in
 * `uploadAtom`, keyed by a client-generated id, and its own
 * `/convert/{job_id}/ws` subscription (`use-socket.ts`) tracking that job's
 * status through to completion.
 *
 * Returns the entry id SYNCHRONOUSLY, with the entry already in the atom in
 * "uploading" -- the POST itself runs in the background. A view that tracks
 * the returned id therefore shows the upload from its first byte; the old
 * shape (resolving the id only after `POST /convert` responded) left the UI
 * with nothing to render for the whole upload of a large file, which read
 * as "I dropped a file and nothing happened".
 */
export const uploadFile = (file: File, options: UploadOptions = {}): string => {
  const id = createId()
  files.set(id, { file, options })

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
      inspection: options.inspection,
      logs: [],
    }
  })

  void performUpload(id, file, options)
  return id
}

const performUpload = async (
  id: string,
  file: File,
  options: UploadOptions
): Promise<void> => {
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

    const response = await apiFetch(`${API_URL}/convert`, {
      method: "POST",
      body: formData,
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
}

export const deleteUpload = (id: string): void => {
  stopTracking(id)
  files.delete(id)
  blobs.delete(id)
  store.set(uploadAtom, (draft) => {
    delete draft[id]
  })
}

export const retryUpload = (id: string): string | undefined => {
  const cached = files.get(id)
  deleteUpload(id)
  // Retrying mints a fresh id via uploadFile() rather than reusing `id` --
  // a stale in-flight status push for the old id (unlikely but possible)
  // would otherwise resurrect a deleted atom entry. The new id is returned
  // so a view tracking the old entry can follow the retried one.
  return cached ? uploadFile(cached.file, cached.options) : undefined
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
    // The conversion already succeeded, and the bytes are safely cached in
    // `blobs` -- only the local save step failed. Log for diagnosis but
    // deliberately don't set `status: "error"` here: that would point the
    // UI at "Try again", which re-runs the entire upload+conversion and
    // can't fix a save-dialog failure. Leaving `status: "ready"` keeps the
    // "Save" action available so the user can retry just this step.
    console.error("Failed to save converted corpus file:", error)
  }
}

/**
 * Manually publishes (or retries publishing) a completed conversion's
 * `.corpus` archive to the Hugging Face Hub storage repo -- triggered by
 * the "Publish to Hugging Face" action in the result panel, never
 * automatically. The outcome lands in `entry.storage` ("stored" with the
 * Hub download URL, or "skipped" with the reason and a retry available);
 * either way the local download/save flow is unaffected.
 */
export const publishUpload = async (id: string): Promise<void> => {
  const entry = store.get(uploadAtom)[id]
  // Needs a finished server-side job to publish from, and only one publish
  // in flight per entry -- a second click while "running" is a no-op.
  if (!entry?.jobId || entry.storage?.status === "running") return
  const { jobId } = entry

  updateEntry(id, (draft) => {
    draft.storage = { status: "running" }
  })
  const storage = await publishConversion(jobId)
  updateEntry(id, (draft) => {
    draft.storage = storage
  })
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
    const response = await apiFetch(`${API_URL}/convert/${jobId}`)
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
    // see jobs.py), or the result was otherwise reaped. There's nothing left
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
    for (const entry of persisted) {
      // A reload mid-publish leaves a persisted "running" storage outcome
      // with no fetch behind it anymore -- clear it so the manual "Publish
      // to Hugging Face" action reappears instead of a stuck spinner.
      if (entry.storage?.status === "running") entry.storage = undefined
      draft[entry.id] = entry
    }
  })

  for (const entry of persisted) {
    if (!entry.jobId) continue
    if (
      entry.status === "queued" ||
      entry.status === "converting" ||
      entry.status === "validating"
    ) {
      // Still in flight as of the last session -- resume live tracking.
      // `websocket.py` sends the job's current status as soon as this
      // connects, so this also self-corrects if it actually finished (or
      // failed, or the server restarted and 404s) while the app was closed.
      // A reload mid-"validating" lands here too: the socket re-pushes
      // "succeeded", which re-runs validation and the download from scratch.
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
