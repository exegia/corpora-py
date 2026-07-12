import { atomWithImmer } from "jotai-immer"

// "uploading"/"queued"/"converting" mirror the client-side upload phase and
// the server's own queued/running states (see JobStatus in use-socket.ts) --
// "queued" covers the gap between the POST /convert response and the first
// WebSocket push. "ready" means the server finished and the `.corpus` bytes
// are already downloaded into memory, but the local save-to-disk step
// hasn't completed yet (either still in flight or failed and awaiting a
// manual retry via `useUpload().saveUpload`) -- deliberately distinct from
// "error", since a save-dialog failure doesn't mean the conversion itself
// needs to be redone.
export type UploadStatus =
  "uploading" | "queued" | "converting" | "ready" | "success" | "error"

export type UploadEntry = {
  id: string
  name: string
  size: number
  type: string
  status: UploadStatus
  progress: number
  error: string | null
  /** Coarse conversion checkpoints returned by the API. */
  logs?: string[]
  /** Last coarse stage message reported by the server (see `JobStatusMessage.last_log`). */
  lastLog?: string | null
  /** Set once conversion succeeds -- the resulting `.corpus` archive's name/size. */
  corpusName?: string
  corpusSize?: number
  /**
   * The server-assigned job id and its `/convert/{id}/ws` path, set once
   * `POST /convert` responds. Kept in the atom (not just in `useUpload`'s
   * closures) so this entry is fully serializable for the localStorage
   * history in `use-upload.ts` -- resuming a job or re-downloading a
   * "ready" file after a page reload needs both, since the in-memory blob
   * cache and WebSocket subscription don't survive one.
   */
  jobId?: string
  wsPath?: string
}

// Keyed by upload id (not an array) so `useUpload` can update one entry via
// immer without re-deriving the whole list, and so multiple concurrent
// uploads never collide on index-based lookups.
export const uploadAtom = atomWithImmer<Record<string, UploadEntry>>({})
