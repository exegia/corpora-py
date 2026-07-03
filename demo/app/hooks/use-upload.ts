import { useAtom } from "jotai"
import { useCallback, useRef } from "react"
import { uploadAtom } from "../atoms/upload-atom"
import { API_URL } from "../types/socket"
import { subscribeJobStatus, type JobStatusMessage } from "./use-socket"

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

  const stopTracking = useCallback((id: string) => {
    unsubscribersRef.current.get(id)?.()
    unsubscribersRef.current.delete(id)
    filesRef.current.delete(id)
  }, [])

  const trackJob = useCallback(
    (id: string, jobId: string, wsPath: string) => {
      const wsUrl = `${API_URL.replace(/^http/, "ws")}${wsPath}`

      const handleMessage = (message: JobStatusMessage) => {
        if (message.status === "running") {
          setUploads((draft) => {
            const entry = draft[id]
            if (!entry) return
            entry.status = "converting"
            // The server has no progress hook (see JobStatus's docstring in
            // use-socket.ts) -- this is a coarse stage marker, not a real
            // completion percentage.
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

              setUploads((draft) => {
                const entry = draft[id]
                if (!entry) return
                entry.status = "success"
                entry.progress = 100
                entry.corpusName = filename
                entry.corpusSize = blob.size
              })

              await saveCorpusFile(filename, blob)
            } catch (error) {
              setUploads((draft) => {
                const entry = draft[id]
                if (!entry) return
                entry.status = "error"
                entry.error = error instanceof Error ? error.message : String(error)
              })
            } finally {
              stopTracking(id)
            }
          })()
        }
      }

      unsubscribersRef.current.set(id, subscribeJobStatus(wsUrl, handleMessage))
    },
    [setUploads, stopTracking],
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

  return { uploads, uploadFile, deleteUpload, retryUpload }
}

export default useUpload
