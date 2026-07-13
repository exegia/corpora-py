import type { UploadEntry } from "~/lib/atoms/upload-atom"

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
  /** One-line detail shown under the label, when known. */
  detail?: string
  state: StageState
}

const WARNING_PATTERN = /\bwarn(ing)?\b/i

/**
 * Maps a tracked upload onto the visible stage-by-stage pipeline. Every
 * stage corresponds to a real observable event (client-side validation, the
 * POST /convert round-trip, the server's coarse queued/running/succeeded/
 * failed states, and the archive download) -- nothing here is simulated.
 *
 * The server has no progress hook (see use-socket.ts), so the "Converting"
 * stage carries the server's own coarse log checkpoints as its detail
 * rather than a fake percentage.
 */
export const deriveStages = (entry: UploadEntry): Stage[] => {
  const { status, error, jobId, sourceFormat, logs, lastLog } = entry

  const failed = status === "error"
  // No job id means the failure happened during (or before) the POST --
  // the server never accepted the file.
  const failedBeforeServer = failed && !jobId
  const done = status === "ready" || status === "success"
  const serverLogsHaveWarning = (logs ?? []).some((line) =>
    WARNING_PATTERN.test(line)
  )

  const uploadState: StageState = failedBeforeServer
    ? "failed"
    : status === "uploading"
      ? "active"
      : "completed"

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

  const downloadState: StageState = done
    ? "completed"
    : failed
      ? "pending"
      : "pending"

  return [
    {
      id: "received",
      label: "File received",
      detail: entry.name,
      state: "completed"
    },
    {
      id: "validated",
      label: "File type validated",
      detail: sourceFormat ? `Detected source format: ${sourceFormat}` : undefined,
      state: sourceFormat ? "completed" : failedBeforeServer ? "failed" : "completed"
    },
    {
      id: "upload",
      label: "Uploaded to conversion service",
      detail: failedBeforeServer ? (error ?? undefined) : undefined,
      state: uploadState
    },
    {
      id: "queued",
      label: "Queued for conversion",
      detail: jobId ? `Job ${jobId}` : undefined,
      state: queuedState
    },
    {
      id: "converting",
      label: "Converting to .corpus",
      detail:
        failed && jobId
          ? (error ?? undefined)
          : convertingState === "warning" && !done
            ? (lastLog ?? "Completed with warnings")
            : done && serverLogsHaveWarning
              ? "Completed with warnings"
              : (lastLog ?? undefined),
      state: convertingState
    },
    {
      id: "download",
      label: "Archive downloaded",
      detail: entry.corpusName,
      state: downloadState
    }
  ]
}

/** The stage a failed run stopped at, for plain-language error reporting. */
export const failedStage = (stages: Stage[]): Stage | undefined =>
  stages.find((stage) => stage.state === "failed")
