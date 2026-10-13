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
  /** Last coarse stage message the server logged for this job, or null if none yet. */
  last_log: string | null
  download_ready: boolean
}

export type WebSocketStatus = "idle" | "connecting" | "open" | "closed" | "error"

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
  onStatusChange?: (status: WebSocketStatus) => void,
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
