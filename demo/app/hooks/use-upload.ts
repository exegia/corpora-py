import { useAtom } from "jotai"
import { useCallback, useEffect, useRef } from "react"
import { uploadAtom, type UploadEntry } from "../atoms/upload-atom"
import { API_URL } from "../types/socket"
import { subscribeJobStatus, type JobStatusMessage } from "./use-socket"

// Where past-conversion history is mirrored so it survives a page reload or
// app relaunch. `corpora-api`'s `JobManager` (see jobs.py) is in-memory only
// -- this is deliberately NOT trying to survive a server restart too; if the
// server process restarts, `GET /convert/{id}` 404s for every job it used to
// know about (even though the finished `.corpus` file is often still on
// disk), and the reconcile pass below drops those entries rather than
// pretend they're recoverable.
const STORAGE_KEY = "corpora:uploads"

const loadPersistedUploads = (): UploadEntry[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as UploadEntry[]) : []
  } catch {
    return []
  }
}

const savePersistedUploads = (uploads: Record<string, UploadEntry>): void => {
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

const createId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`

// Mirrors `_EXTENSION_TO_FORMAT` in packages/admin/src/admin/services/api.py's
// `SourceFormat` enum values -- `POST /convert`'s `source_format` field is
// required (there's no server-side auto-detection), so the UI has to supply
// one. `.xml` maps to "tei" rather than the generic "xml" on purpose: XML has
// no Text-Fabric converter yet (see packages/admin/CLAUDE.md's "Known gaps"),
// TEI documents are almost always authored with a plain `.xml` extension,
// and TEI is the only working converter a bare `.xml` file could plausibly
// mean.
const EXTENSION_TO_FORMAT: Record<string, string> = {
  ".epub": "epub",
  ".html": "html",
  ".htm": "html",
  ".xml": "tei",
  ".tei": "tei",
  ".pdf": "pdf",
  ".txt": "plain",
  ".text": "plain",
}

const detectSourceFormat = (filename: string): string => {
  const match = /\.[^./]+$/.exec(filename)
  const extension = (match?.[0] ?? "").toLowerCase()
  const format = EXTENSION_TO_FORMAT[extension]
  if (!format) {
    throw new Error(
      `Can't auto-detect a source format from "${filename}" (extension "${extension}"). ` +
        `Recognized: ${Object.keys(EXTENSION_TO_FORMAT).join(", ")}`,
    )
  }
  return format
}

type SaveFilePicker = (options: {
  suggestedName: string
  types: { description: string; accept: Record<string, string[]> }[]
}) => Promise<{ createWritable: () => Promise<{ write: (data: Blob) => Promise<void>; close: () => Promise<void> }> }>

// Saves via the File System Access API's native save-as dialog where
// available (desktop webviews backing ElectroBun); falls back to a plain
// anchor-download for browsers that don't support it.
const saveCorpusFile = async (filename: string, blob: Blob): Promise<void> => {
  const showSaveFilePicker = (window as unknown as { showSaveFilePicker?: SaveFilePicker })
    .showSaveFilePicker

  if (showSaveFilePicker) {
    try {
      const handle = await showSaveFilePicker({
        suggestedName: filename,
        types: [{ description: "Corpus archive", accept: { "application/octet-stream": [".corpus"] } }],
      })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      return
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return
      throw error
    }
  }

  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

type ConvertResponse = { job_id: string; status_url: string; ws_url: string }

/**
 * Uploads a file to the `corpora-api` conversion endpoint (`POST /convert`,
 * see `admin/services/api.py`) and saves the resulting `.corpus` archive via
 * a native save-as dialog.
 *
 * `corpora-api` requires a Supabase JWT by default (`AUTH_REQUIRED=true`,
 * see the root CLAUDE.md's "Auth" section) -- this demo has no Supabase
 * session to attach one from yet, so run the server locally with
 * `AUTH_REQUIRED=false` (see README.md) until real auth is wired in here.
 *
 * Multiple files can be in flight at once -- each gets its own entry in
 * `uploadAtom`, keyed by a client-generated id, and its own
 * `/convert/{job_id}/ws` subscription (`use-socket.ts`) tracking that job's
 * status through to completion.
 */
export const useUpload = () => {
  const [uploads, setUploads] = useAtom(uploadAtom)
  // The real `File` (needed to retry) never goes into the atom -- atoms hold
  // serializable UI state.
  const filesRef = useRef(new Map<string, File>())
  // Closes the job-status socket early if the upload is deleted before the
  // job reaches a terminal state.
  const unsubscribersRef = useRef(new Map<string, () => void>())
  // The downloaded `.corpus` bytes, cached once the server-side conversion
  // succeeds and the download completes. Kept out of the atom (blobs aren't
  // serializable) so `saveUpload` can retry just the local save-to-disk step
  // -- which can fail independently of the conversion (e.g. the save
  // dialog is dismissed with an error, or write permission is denied) --
  // without re-uploading and re-converting the whole file.
  const blobsRef = useRef(new Map<string, { blob: Blob; filename: string }>())
  // Mirrors `uploads` synchronously so callbacks that must stay referentially
  // stable (`trySave`, called from the WebSocket handler and from a rehydrated
  // page load) can read the latest entry without depending on `uploads`
  // itself, which would otherwise force `trackJob`/`trySave` to be redefined
  // -- and every subscribed WebSocket handler along with them -- on every
  // status update.
  const uploadsRef = useRef(uploads)
  uploadsRef.current = uploads

  const stopTracking = useCallback((id: string) => {
    unsubscribersRef.current.get(id)?.()
    unsubscribersRef.current.delete(id)
    filesRef.current.delete(id)
  }, [])

  const trySave = useCallback(
    async (id: string) => {
      let cached = blobsRef.current.get(id)

      if (!cached) {
        // Nothing cached in this process -- either the page was reloaded
        // since the conversion succeeded (blobs don't survive that, unlike
        // the persisted atom entry) or this is a retry after a previous
        // save already cleared the cache. Re-fetch using the job id, which
        // *is* persisted -- the `.corpus` file survives in `_RESULTS_ROOT`
        // on the server independent of this client's lifetime.
        const entry = uploadsRef.current[id]
        if (!entry?.jobId || !entry.corpusName) return
        try {
          const response = await fetch(`${API_URL}/convert/${entry.jobId}/download`)
          if (!response.ok) throw new Error(`Download failed (${response.status})`)
          cached = { blob: await response.blob(), filename: entry.corpusName }
          blobsRef.current.set(id, cached)
        } catch (error) {
          console.error("Failed to re-download converted corpus file:", error)
          return
        }
      }

      try {
        await saveCorpusFile(cached.filename, cached.blob)
        setUploads((draft) => {
          const entry = draft[id]
          if (!entry) return
          entry.status = "success"
        })
        blobsRef.current.delete(id)
      } catch (error) {
        // The conversion already succeeded and the bytes are safely cached
        // in `blobsRef` -- only the local save step failed. Log for
        // diagnosis but deliberately don't set `status: "error"` here: that
        // would point the UI at "Try again", which re-runs the entire
        // upload+conversion and can't fix a save-dialog failure. Leaving
        // `status: "ready"` keeps the "Save" action available so the user
        // can retry just this step.
        console.error("Failed to save converted corpus file:", error)
      }
    },
    [setUploads],
  )

  const trackJob = useCallback(
    (id: string, jobId: string, wsPath: string) => {
      const wsUrl = `${API_URL.replace(/^http/, "ws")}${wsPath}`

      const handleMessage = (message: JobStatusMessage) => {
        // Applies regardless of which branch below fires -- the server can
        // push an update with the same `status` but a new `last_log` line
        // (see websocket.py), and the UI should reflect that either way.
        setUploads((draft) => {
          const entry = draft[id]
          if (entry) entry.lastLog = message.last_log
        })

        if (message.status === "running") {
          setUploads((draft) => {
            const entry = draft[id]
            if (!entry) return
            entry.status = "converting"
            // The server has no progress hook (see JobStatus's docstring in
            // use-socket.ts) -- this is a coarse stage marker, not a real
            // completion percentage. The file card renders an indeterminate
            // animation while "converting" rather than trusting this number
            // as real progress.
            entry.progress = 60
          })
          return
        }

        if (message.status === "failed") {
          setUploads((draft) => {
            const entry = draft[id]
            if (!entry) return
            entry.status = "error"
            entry.error = message.error ?? "Conversion failed"
          })
          stopTracking(id)
          return
        }

        if (message.status === "succeeded") {
          void (async () => {
            try {
              const response = await fetch(`${API_URL}/convert/${jobId}/download`)
              if (!response.ok) throw new Error(`Download failed (${response.status})`)
              const blob = await response.blob()
              const filename = `${message.name}.corpus`

              // The conversion succeeded and the bytes are in hand -- from
              // here, only the local save-to-disk step can still fail, and
              // that must never downgrade this to "error" (see `trySave`).
              blobsRef.current.set(id, { blob, filename })
              setUploads((draft) => {
                const entry = draft[id]
                if (!entry) return
                entry.status = "ready"
                entry.progress = 100
                entry.corpusName = filename
                entry.corpusSize = blob.size
              })
            } catch (error) {
              // Only a genuine server-side/network failure to fetch the
              // already-converted archive lands here -- there's nothing
              // cached to retry locally, so "Try again" re-running the
              // whole upload is the correct recovery.
              setUploads((draft) => {
                const entry = draft[id]
                if (!entry) return
                entry.status = "error"
                entry.error = error instanceof Error ? error.message : String(error)
              })
              stopTracking(id)
              return
            }

            stopTracking(id)
            await trySave(id)
          })()
        }
      }

      unsubscribersRef.current.set(id, subscribeJobStatus(wsUrl, handleMessage))
    },
    [setUploads, stopTracking, trySave],
  )

  const uploadFile = useCallback(
    async (file: File): Promise<string> => {
      const id = createId()
      filesRef.current.set(id, file)

      setUploads((draft) => {
        draft[id] = {
          id,
          name: file.name,
          size: file.size,
          type: file.type,
          status: "uploading",
          progress: 0,
          error: null,
        }
      })

      try {
        const sourceFormat = detectSourceFormat(file.name)

        const formData = new FormData()
        formData.append("file", file)
        formData.append("source_format", sourceFormat)
        formData.append("name", file.name.replace(/\.[^./]+$/, ""))

        const response = await fetch(`${API_URL}/convert`, { method: "POST", body: formData })
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { detail?: string }
          throw new Error(body.detail ?? `Upload failed (${response.status})`)
        }

        const { job_id: jobId, ws_url: wsPath } = (await response.json()) as ConvertResponse

        setUploads((draft) => {
          const entry = draft[id]
          if (!entry) return
          entry.status = "queued"
          entry.progress = 20
          // Persisted so a reload can resume tracking (still in flight) or
          // re-check/re-download (already "ready") this job -- see the
          // localStorage sync effect below.
          entry.jobId = jobId
          entry.wsPath = wsPath
        })

        trackJob(id, jobId, wsPath)
      } catch (error) {
        setUploads((draft) => {
          const entry = draft[id]
          if (!entry) return
          entry.status = "error"
          entry.error = error instanceof Error ? error.message : String(error)
        })
        filesRef.current.delete(id)
      }

      return id
    },
    [setUploads, trackJob],
  )

  const deleteUpload = useCallback(
    (id: string) => {
      stopTracking(id)
      blobsRef.current.delete(id)
      setUploads((draft) => {
        delete draft[id]
      })
    },
    [setUploads, stopTracking],
  )

  const retryUpload = useCallback(
    (id: string) => {
      const file = filesRef.current.get(id)
      stopTracking(id)
      blobsRef.current.delete(id)
      setUploads((draft) => {
        delete draft[id]
      })
      // Retrying mints a fresh id via uploadFile() rather than reusing `id`
      // -- a stale in-flight status push for the old id (unlikely but
      // possible) would otherwise resurrect a deleted atom entry.
      if (file) void uploadFile(file)
    },
    [setUploads, stopTracking, uploadFile],
  )

  // Retries just the local save-to-disk step for an entry stuck in "ready"
  // (conversion succeeded, `.corpus` bytes are cached, but the save dialog
  // failed) -- see `trySave`'s docstring for why this is separate from
  // `retryUpload`.
  const saveUpload = useCallback((id: string) => void trySave(id), [trySave])

  // Confirms a rehydrated "ready" entry (server said "succeeded" in a past
  // session) is still actually downloadable before leaving it in the list.
  // Deliberately does NOT auto-fetch the blob or pop the save dialog here --
  // only `GET /convert/{id}` (a cheap status check), not `/download` -- so
  // reopening the app after several past conversions doesn't fire off a
  // pile of save-as dialogs unprompted. `saveUpload` fetches the bytes
  // on-demand (see `trySave`) once the user actually clicks "Save file".
  const reconcileReady = useCallback(
    async (id: string, jobId: string) => {
      try {
        const response = await fetch(`${API_URL}/convert/${jobId}`)
        if (!response.ok) throw new Error(`Job lookup failed (${response.status})`)
        const status = (await response.json()) as { status: string; download_ready: boolean }
        if (status.status !== "succeeded" || !status.download_ready) {
          throw new Error(`Job is ${status.status}, not ready`)
        }
      } catch {
        // The server restarted (its in-memory `JobManager` forgot this job
        // -- see jobs.py) or the result was otherwise reaped. There's
        // nothing left to save, so drop this history entry rather than
        // leave a permanently broken "Save" button behind.
        setUploads((draft) => {
          delete draft[id]
        })
      }
    },
    [setUploads],
  )

  // Rehydrates past-conversion history from localStorage once, on mount.
  // Runs after every render but bails immediately past the first call --
  // a plain `useEffect(..., [])` would be equivalent, but this also
  // tolerates `trackJob`/`reconcileReady` changing identity without
  // re-running the hydration itself.
  const hydratedRef = useRef(false)
  useEffect(() => {
    if (hydratedRef.current) return
    hydratedRef.current = true

    const persisted = loadPersistedUploads()
    if (persisted.length === 0) return

    setUploads((draft) => {
      for (const entry of persisted) draft[entry.id] = entry
    })

    for (const entry of persisted) {
      if (!entry.jobId) continue
      if (entry.status === "queued" || entry.status === "converting") {
        // Still in flight as of the last session -- resume live tracking.
        // `websocket.py` sends the job's current status as soon as this
        // connects, so this also self-corrects if it actually finished
        // (or failed, or the server restarted and 4404s) while the app
        // was closed.
        if (entry.wsPath) trackJob(entry.id, entry.jobId, entry.wsPath)
      } else if (entry.status === "ready") {
        void reconcileReady(entry.id, entry.jobId)
      }
    }
  }, [trackJob, reconcileReady, setUploads])

  // Mirrors `uploads` to localStorage on every change so it survives a
  // reload/relaunch -- see `savePersistedUploads`'s docstring for what's
  // deliberately excluded (and the module docstring for why this doesn't
  // try to survive a *server* restart).
  useEffect(() => {
    savePersistedUploads(uploads)
  }, [uploads])

  return { uploads, uploadFile, deleteUpload, retryUpload, saveUpload }
}

export default useUpload
