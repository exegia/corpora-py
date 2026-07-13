import type { UploadEntry } from "~/lib/atoms/upload-atom"
import { formatBytes } from "~/lib/hooks/use-file-upload"
import type { LogLine } from "./log-console"

/**
 * Client-side state model for the upload -> conversion experience.
 * See README.md in this directory for the full transition diagram.
 *
 * `ConvertView` is the coarse layout state of the /corpus/convert route,
 * derived (never stored) from the tracked `UploadEntry`:
 *
 * - "empty":      no file accepted yet -- show the drag-and-drop box. A
 *                 rejected (unsupported) file stays in this view with an
 *                 inline error.
 * - "processing": a valid file was accepted and the upload/conversion
 *                 pipeline is running ("uploading" | "queued" | "converting").
 * - "completed":  the `.corpus` bytes are downloaded ("ready") or already
 *                 saved to disk ("success").
 * - "failed":     the upload or conversion errored ("error").
 */
export type ConvertView = "empty" | "processing" | "completed" | "failed"

export const deriveView = (entry: UploadEntry | undefined): ConvertView => {
  if (!entry) return "empty"
  if (entry.status === "error") return "failed"
  if (entry.status === "ready" || entry.status === "success") return "completed"
  return "processing"
}

export type StageState =
  | "pending"
  | "active"
  | "completed"
  | "warning"
  | "failed"

export type Stage = {
  id: string
  label: string
  state: StageState
  /** The real log lines belonging to this stage, shown inline under it. */
  logs: LogLine[]
}

const WARNING_PATTERN = /\bwarn(ing)?\b/i
const ERROR_PATTERN = /\b(error|fail(ed|ure)?)\b/i

const serverLineTone = (line: string): LogLine["tone"] =>
  WARNING_PATTERN.test(line)
    ? "warning"
    : ERROR_PATTERN.test(line)
      ? "error"
      : "info"

/**
 * Maps a tracked upload onto the visible stage-by-stage pipeline. Every
 * stage corresponds to a real observable event (client-side validation, the
 * POST /convert round-trip, the server's coarse queued/running/succeeded/
 * failed states, and the archive download) and carries that event's log
 * lines -- nothing here is simulated.
 *
 * The server has no progress hook (see use-socket.ts), so the "Converting"
 * stage carries the server's own coarse log checkpoints rather than a fake
 * percentage.
 */
export const deriveStages = (entry: UploadEntry): Stage[] => {
  const { status, error, jobId, sourceFormat, logs } = entry

  const failed = status === "error"
  // No job id means the failure happened during (or before) the POST --
  // the server never accepted the file.
  const failedBeforeServer = failed && !jobId
  const done = status === "ready" || status === "success"
  const serverLogs = logs ?? []
  const serverLogsHaveWarning = serverLogs.some((line) =>
    WARNING_PATTERN.test(line)
  )

  const uploadState: StageState = failedBeforeServer
    ? "failed"
    : status === "uploading"
      ? "active"
      : "completed"

  const uploadLogs: LogLine[] = [
    { text: "Uploading to POST /convert…", tone: "info" }
  ]
  if (failedBeforeServer) {
    uploadLogs.push(
      { text: `Error: ${error ?? "Upload failed"}`, tone: "error" },
      {
        text: "Suggested action: check that the conversion API is running, then retry.",
        tone: "info"
      }
    )
  }

  const queuedState: StageState = failedBeforeServer
    ? "pending"
    : status === "uploading"
      ? "pending"
      : status === "queued"
        ? "active"
        : "completed"

  const convertingState: StageState =
    failed && jobId
      ? "failed"
      : status === "converting"
        ? serverLogsHaveWarning
          ? "warning"
          : "active"
        : done
          ? serverLogsHaveWarning
            ? "warning"
            : "completed"
          : "pending"

  const convertingLogs: LogLine[] = serverLogs.map((line) => ({
    text: line,
    tone: serverLineTone(line)
  }))
  if (failed && jobId) {
    convertingLogs.push(
      { text: `Error: ${error ?? "Conversion failed"}`, tone: "error" },
      {
        text: "Suggested action: retry the conversion, or replace the file.",
        tone: "info"
      }
    )
  }

  return [
    {
      id: "received",
      label: "File received",
      state: "completed",
      logs: [
        {
          text: `File received: ${entry.name} (${formatBytes(entry.size)})`,
          tone: "info"
        }
      ]
    },
    {
      id: "validated",
      label: "File type validated",
      state: sourceFormat ? "completed" : failedBeforeServer ? "failed" : "completed",
      logs: [
        // ZIP inspection findings (contents inventory, extraction notes)
        // happen as part of validating what the upload actually is.
        ...(entry.inspection ?? []).map(
          (text): LogLine => ({ text, tone: "info" })
        ),
        ...(sourceFormat
          ? [
            {
              text: `File type validated — source format "${sourceFormat}"`,
              tone: "success"
            } satisfies LogLine
          ]
          : [])
      ]
    },
    {
      id: "upload",
      label: "Uploaded to conversion service",
      state: uploadState,
      logs: uploadLogs
    },
    {
      id: "queued",
      label: "Queued for conversion",
      state: queuedState,
      logs: jobId
        ? [
          {
            text: `Job ${jobId} created — tracking status over WebSocket`,
            tone: "success"
          }
        ]
        : []
    },
    {
      id: "converting",
      label: "Converting to .corpus",
      state: convertingState,
      logs: convertingLogs
    },
    {
      id: "download",
      label: "Archive downloaded",
      state: done ? "completed" : "pending",
      logs: done
        ? [
          {
            text: `Downloaded ${entry.corpusName ?? "archive"}${
              entry.corpusSize !== undefined
                ? ` (${formatBytes(entry.corpusSize)})`
                : ""
            }`,
            tone: "success"
          }
        ]
        : []
    }
  ]
}

/** The stage a failed run stopped at, for plain-language error reporting. */
export const failedStage = (stages: Stage[]): Stage | undefined =>
  stages.find((stage) => stage.state === "failed")
