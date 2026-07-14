import { atomWithImmer } from "jotai-immer"

// "uploading"/"queued"/"converting" mirror the client-side upload phase and
// the server's own queued/running states (see JobStatus in use-socket.ts) --
// "queued" covers the gap between the POST /convert response and the first
// WebSocket push. "validating" covers the POST /validate round-trip after
// the server reports "succeeded" (the result archive is checked through the
// full .tf -> .cfm load cycle before download). "ready" means the server
// finished and the `.corpus` bytes are already downloaded into memory, but
// the local save-to-disk step hasn't completed yet (either still in flight
// or failed and awaiting a manual retry via `useUpload().saveUpload`) --
// deliberately distinct from "error", since a save-dialog failure doesn't
// mean the conversion itself needs to be redone.
export type UploadStatus =
  | "uploading"
  | "queued"
  | "converting"
  | "validating"
  | "ready"
  | "success"
  | "error"

/**
 * Verdict of the post-conversion `POST /validate` round-trip (see
 * `admin.services.validation_api`). "skipped" means the request itself
 * failed (network error, server too old to know /validate) -- deliberately
 * distinct from "invalid", which is the server saying the corpus does not
 * round-trip the `.tf -> .cfm -> mmap` load cycle. A validation problem
 * never blocks the download/save flow: the verdict is an annotation on the
 * finished conversion, not a gate.
 */
export type ValidationOutcome = {
  status: "running" | "valid" | "invalid" | "skipped"
  /** Why the corpus failed validation, or why the check was skipped. */
  reasons?: string[]
  /** Corpus stats from a successful validation (see CorpusStats server-side). */
  stats?: Record<string, number>
}

export type UploadEntry = {
  id: string
  name: string
  size: number
  type: string
  status: UploadStatus
  progress: number
  error: string | null
  /** `File.lastModified` of the source file, when the browser provided one. */
  lastModified?: number
  /** When this upload was started on the client (`Date.now()`). */
  uploadedAt?: number
  /** Source format sent as `source_format` to `POST /convert` (see source-format.ts). */
  sourceFormat?: string
  /**
   * Client-side pre-upload findings (ZIP contents inventory, extraction
   * notes -- see inspect-zip.ts), shown under the "File type validated"
   * stage in the conversion console.
   */
  inspection?: string[]
  /** Coarse conversion checkpoints returned by the API. */
  logs?: string[]
  /** Last coarse stage message reported by the server (see `JobStatusMessage.last_log`). */
  lastLog?: string | null
  /**
   * Post-conversion validation verdict, set by the manager once the server
   * reports "succeeded" (absent on entries converted before validation
   * existed). Serializable, so it persists with the rest of the entry.
   */
  validation?: ValidationOutcome
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
