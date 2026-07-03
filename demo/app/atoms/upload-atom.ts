import { atomWithImmer } from "jotai-immer"

// "uploading"/"queued"/"converting" mirror the client-side upload phase and
// the server's own queued/running states (see JobStatus in use-socket.ts) --
// "queued" covers the gap between the POST /convert response and the first
// WebSocket push.
export type UploadStatus = "uploading" | "queued" | "converting" | "success" | "error"

export type UploadEntry = {
  id: string
  name: string
  size: number
  type: string
  status: UploadStatus
  progress: number
  error: string | null
  /** Set once conversion succeeds -- the resulting `.corpus` archive's name/size. */
  corpusName?: string
  corpusSize?: number
}

// Keyed by upload id (not an array) so `useUpload` can update one entry via
// immer without re-deriving the whole list, and so multiple concurrent
// uploads never collide on index-based lookups.
export const uploadAtom = atomWithImmer<Record<string, UploadEntry>>({})
