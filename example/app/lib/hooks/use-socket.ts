import { useEffect, useState } from "react"

// Mirrors `admin.services.jobs.ConversionJob.to_dict()` -- see
// packages/admin/src/admin/services/jobs.py. No progress percentage: the
// conversion pipeline has no progress hook, so the server only ever reports
// these four coarse states (see admin/services/websocket.py's docstring).
export type JobStatus = "queued" | "running" | "succeeded" | "failed"

export type JobStatusMessage = {
  id: string
  source_format: string
  name: string
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
   * Derived from the user-supplied `name`, not the upload filename -- so a
   * client that stores only this field never persists the original source
   * file as the library object (see issue #108). Stable across the job's
   * lifetime; the download route's `Content-Disposition` echoes it back.
   */
  result_filename: string
  download_ready: boolean
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
 * Polling equivalent of `subscribeJobStatus`, driving `GET /convert/{id}`
 * on an interval until the job reaches a terminal state.
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
 */
export const pollJobStatus = (
  fetchStatus: () => Promise<JobStatusMessage>,
  onMessage: (message: JobStatusMessage) => void,
  intervalMs = 2000
): (() => void) => {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined

  const tick = async () => {
    if (stopped) return
    try {
      const message = await fetchStatus()
      if (stopped) return
      onMessage(message)
      if (TERMINAL_STATUSES.includes(message.status)) return
    } catch {
      // Transient network/5xx errors shouldn't kill tracking -- keep polling
      // and let the next tick recover. A job that genuinely vanished
      // (instance eviction) stays "converting" rather than being reported as
      // a failure we can't actually confirm.
    }
    timer = setTimeout(() => void tick(), intervalMs)
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
