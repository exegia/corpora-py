import { useEffect, useState } from "react"
import type { SourceReliability } from "~/lib/atoms/upload-atom"

// Mirrors `admin.services.jobs.ConversionJob.to_dict()` -- see
// packages/admin/src/admin/services/jobs.py. Job status has four coarse
// states; forced PDF OCR also carries confirmed page counts.
export type JobStatus = "queued" | "running" | "succeeded" | "failed"

export type JobStatusMessage = {
  id: string
  source_format: string
  name: string
  /**
   * The human-readable title derived from the source document's own
   * metadata (TEI `titleStmt`, PDF `info.title`, HTML `<title>`, EPUB
   * `dc:title`), falling back to the request `name` / filename stem (see
   * issue #109). `null` until the worker thread extracts it; set on the
   * running/succeeded status. This is what `manifest.name` carries and what
   * a library should display -- prefer it over `name` when present.
   */
  display_name: string | null
  status: JobStatus
  created_at: number
  started_at: number | null
  finished_at: number | null
  error: string | null
  /** Complete coarse log history for the job, in server emission order. */
  logs: string[]
  /** Last coarse stage message the server logged for this job, or null if none yet. */
  last_log: string | null
  /**
   * The human-readable filename the client should store the result under
   * (always `*.corpus` for /convert jobs, `*.graph.json` for /ingest jobs).
   * Derived from the display name (or the request `name` before the title
   * is known), not the upload filename -- so a client that stores only
   * this field never persists the original source file as the library
   * object (see issues #108/#109). Stable across the job's lifetime; the
   * download route's `Content-Disposition` echoes it back.
   */
  result_filename: string
  download_ready: boolean
  progress?: {
    completed_pages: number
    total_pages: number | null
    updated_at: number
  } | null
  validation?: {
    valid: boolean
    reasons?: string[]
    stats?: Record<string, number>
    source_reliability?: SourceReliability | null
  } | null
}

export type WebSocketStatus =
  "idle" | "connecting" | "open" | "closed" | "error"

const TERMINAL_STATUSES: JobStatus[] = ["succeeded", "failed"]

/**
 * Opens a plain WebSocket at `url` (a corpora-api `/convert/{job_id}/ws`
 * URL, see `admin/services/websocket.py`) and invokes `onMessage` for every
 * parsed status push, closing automatically once the job reaches a terminal
 * state (mirrors the server's own behavior).
 *
 * This is a plain function, not a hook, so it's the primitive `useWebSocket`
 * below wraps for component use -- `use-upload.ts` needs to open one of
 * these from inside a plain async callback (kicked off per uploaded file),
 * which can't call a React hook.
 */
export const subscribeJobStatus = (
  url: string,
  onMessage: (message: JobStatusMessage) => void,
  onStatusChange?: (status: WebSocketStatus) => void
): (() => void) => {
  onStatusChange?.("connecting")
  const ws = new WebSocket(url)

  ws.addEventListener("open", () => onStatusChange?.("open"))
  ws.addEventListener("error", () => onStatusChange?.("error"))
  ws.addEventListener("close", () => onStatusChange?.("closed"))
  ws.addEventListener("message", (event) => {
    try {
      const message = JSON.parse(event.data as string) as JobStatusMessage
      onMessage(message)
      if (TERMINAL_STATUSES.includes(message.status)) ws.close()
    } catch {
      // Ignore malformed frames rather than crashing the socket.
    }
  })

  return () => ws.close()
}

/**
 * Thrown by a `fetchStatus` implementation when the server says the job no
 * longer exists (a 404 on `GET /convert/{id}` for a job we previously
 * tracked). Unlike a transient network/5xx error, this is terminal: the
 * backend 404s both unknown and foreign jobs (see `_not_found_unless_visible`
 * in `admin/services/api.py`), and a job row can genuinely vanish on
 * instance eviction (`MemoryJobStore`) or a backend restart -- polling
 * harder will never bring it back.
 */
export class JobGoneError extends Error {
  constructor(message = "Conversion job not found") {
    super(message)
    this.name = "JobGoneError"
  }
}

/** Why `pollJobStatus` gave up before reaching a terminal job status. */
export type PollFailureReason =
  /** The server 404'd a job we were tracking -- it no longer exists. */
  | "gone"
  /** No new status or conversion progress within `deadlineMs`. */
  | "timeout"
  /** `maxConsecutiveErrors` fetches failed in a row -- server unreachable. */
  | "unreachable"

export type PollOptions = {
  /** Base interval between successful status checks. */
  intervalMs?: number
  /**
   * Idle budget since the last status/log/progress change. Large forced-OCR
   * conversions can exceed this total runtime while completing pages.
   */
  deadlineMs?: number
  /** Consecutive fetch failures tolerated before giving up as unreachable. */
  maxConsecutiveErrors?: number
  /** Invoked exactly once when the poll gives up; the poll stops after it. */
  onFailure?: (reason: PollFailureReason) => void
}

export const POLL_DEFAULTS = {
  intervalMs: 2000,
  deadlineMs: 15 * 60_000,
  maxConsecutiveErrors: 10,
} as const

/** Error-retry backoff never waits longer than this between attempts. */
const MAX_ERROR_BACKOFF_MS = 10_000

/**
 * Polling equivalent of `subscribeJobStatus`, driving `GET /convert/{id}`
 * on an interval until the job reaches a terminal state -- or until the
 * poll itself gives up: a 404 for a tracked job, an idle deadline,
 * or too many consecutive fetch failures all end tracking via
 * `onFailure` instead of spinning forever. Transient errors back off
 * (doubling up to 10 s) rather than hammering at a fixed rate.
 *
 * Exists because the production API runs on Vercel Functions, which don't
 * support WebSockets at all -- `/convert/{id}/ws` 404s there, so the socket
 * closes immediately and no status ever arrives. On Vercel this is also the
 * only thing that *advances* the conversion: the job runs on a background
 * thread whose instance is frozen between requests, so it only makes
 * progress while a request is in flight (see the root CLAUDE.md's note that
 * the container image, not Functions, is the deployment for heavy
 * conversion work).
 *
 * `fetchStatus` is injected rather than importing `apiFetch` here, so this
 * module stays free of settings/auth concerns like the socket path above.
 * Implementations should throw `JobGoneError` on a 404 so it can be told
 * apart from a transient failure.
 */
export const pollJobStatus = (
  fetchStatus: () => Promise<JobStatusMessage>,
  onMessage: (message: JobStatusMessage) => void,
  options: PollOptions = {}
): (() => void) => {
  const {
    intervalMs = POLL_DEFAULTS.intervalMs,
    deadlineMs = POLL_DEFAULTS.deadlineMs,
    maxConsecutiveErrors = POLL_DEFAULTS.maxConsecutiveErrors,
    onFailure,
  } = options

  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let consecutiveErrors = 0
  let lastActivityAt = Date.now()
  let lastSignature: string | undefined
  let waitingForOcrWorker = false

  const giveUp = (reason: PollFailureReason) => {
    stopped = true
    onFailure?.(reason)
  }

  const tick = async () => {
    if (stopped) return
    if (!waitingForOcrWorker && Date.now() - lastActivityAt > deadlineMs) {
      giveUp("timeout")
      return
    }
    let delay = intervalMs
    try {
      const message = await fetchStatus()
      if (stopped) return
      consecutiveErrors = 0
      const signature = JSON.stringify([message.status, message.last_log, message.progress])
      if (signature !== lastSignature) {
        lastSignature = signature
        lastActivityAt = Date.now()
      }
      waitingForOcrWorker = message.source_format === "pdf" && ["PDF OCR: waiting for worker", "PDF comparison: waiting for independent worker"].includes(message.last_log ?? "")
      onMessage(message)
      if (TERMINAL_STATUSES.includes(message.status)) return
    } catch (error) {
      if (stopped) return
      if (error instanceof JobGoneError) {
        giveUp("gone")
        return
      }
      // Transient network/5xx errors shouldn't kill tracking immediately --
      // back off and let a later tick recover. Only a sustained run of
      // failures (the server is genuinely unreachable) ends the poll.
      consecutiveErrors += 1
      if (consecutiveErrors >= maxConsecutiveErrors) {
        giveUp("unreachable")
        return
      }
      delay = Math.min(intervalMs * 2 ** consecutiveErrors, MAX_ERROR_BACKOFF_MS)
    }
    timer = setTimeout(() => void tick(), delay)
  }

  void tick()

  return () => {
    stopped = true
    if (timer !== undefined) clearTimeout(timer)
  }
}

/**
 * React hook wrapper around `subscribeJobStatus`, for components that want
 * to reactively render a single job's live status. Re-subscribes whenever
 * `url` changes; pass `null`/`undefined` to stay idle (e.g. before a job id
 * is known yet).
 */
export const useWebSocket = (url?: string | null) => {
  const [status, setStatus] = useState<WebSocketStatus>("idle")
  const [lastMessage, setLastMessage] = useState<JobStatusMessage | null>(null)

  useEffect(() => {
    if (!url) {
      setStatus("idle")
      return
    }

    return subscribeJobStatus(url, setLastMessage, setStatus)
  }, [url])

  return { status, lastMessage }
}
