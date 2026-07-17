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
 *                 pipeline is running ("uploading" | "queued" | "converting"
 *                 | "validating").
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
  "pending" | "active" | "completed" | "warning" | "failed"

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
 * failed states, the post-conversion POST /validate verdict, the archive
 * download, and the user-triggered Hugging Face Hub publish via POST
 * /storage) and carries that event's log lines -- nothing here is
 * simulated.
 *
 * The server has no progress hook (see use-socket.ts), so the "Converting"
 * stage carries the server's own coarse log checkpoints rather than a fake
 * percentage.
 */
export const deriveStages = (entry: UploadEntry): Stage[] => {
  const { status, error, jobId, sourceFormat, logs, validation, storage } =
    entry

  const failed = status === "error"
  // No job id means the failure happened during (or before) the POST --
  // the server never accepted the file.
  const failedBeforeServer = failed && !jobId
  const done = status === "ready" || status === "success"
  // "validating" means the server-side conversion already succeeded -- the
  // stages before validation should render as completed, not stuck.
  const conversionDone = done || status === "validating"
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
    { text: "Uploading to POST /convert…", tone: "info" },
  ]
  if (failedBeforeServer) {
    uploadLogs.push(
      { text: `Error: ${error ?? "Upload failed"}`, tone: "error" },
      {
        text: "Suggested action: check that the conversion API is running, then retry.",
        tone: "info",
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
        : conversionDone
          ? serverLogsHaveWarning
            ? "warning"
            : "completed"
          : "pending"

  const convertingLogs: LogLine[] = serverLogs.map((line) => ({
    text: line,
    tone: serverLineTone(line),
  }))
  if (failed && jobId) {
    convertingLogs.push(
      { text: `Error: ${error ?? "Conversion failed"}`, tone: "error" },
      {
        text: "Suggested action: retry the conversion, or replace the file.",
        tone: "info",
      }
    )
  }

  // Post-conversion validation (POST /validate by job id): "invalid" marks
  // the stage failed but never blocks the download/save flow -- the verdict
  // annotates the finished conversion, it doesn't gate it (see manager.ts).
  // Entries converted before validation existed have no `validation` at all
  // and get an honest warning rather than a pretend pass.
  const validationState: StageState =
    status === "validating" || validation?.status === "running"
      ? "active"
      : validation?.status === "valid"
        ? "completed"
        : validation?.status === "invalid"
          ? "failed"
          : validation?.status === "skipped"
            ? "warning"
            : done
              ? "warning"
              : "pending"

  const validationLogs: LogLine[] = []
  if (status === "validating" || validation) {
    validationLogs.push({
      text: "Validating dataset — POST /validate (full .tf → .cfm load cycle)…",
      tone: "info",
    })
  }
  switch (validation?.status) {
    case "valid": {
      const stats = validation.stats
      validationLogs.push({
        text: stats
          ? `Corpus validated — ${(stats.max_slot ?? 0).toLocaleString()} slots, ${
              stats.node_types ?? 0
            } node types, ${
              (stats.node_features ?? 0) + (stats.edge_features ?? 0)
            } features`
          : "Corpus validated.",
        tone: "success",
      })
      break
    }
    case "invalid":
      validationLogs.push(
        { text: "Corpus failed validation:", tone: "error" },
        ...(validation.reasons ?? []).map((reason): LogLine => ({
          text: reason,
          tone: "error",
        })),
        {
          text: "Suggested action: the archive can still be saved, but apps may fail to load it — retry the conversion or check the source document.",
          tone: "info",
        }
      )
      break
    case "skipped":
      validationLogs.push({
        text: `Validation could not run: ${
          validation.reasons?.[0] ?? "unknown error"
        }. The archive is still downloadable.`,
        tone: "warning",
      })
      break
  }
  if (!validation && done) {
    validationLogs.push({
      text: "No validation recorded for this run (converted before validation was added).",
      tone: "warning",
    })
  }

  // Hugging Face Hub publish (POST /storage by job id): a MANUAL step the
  // user triggers from the result panel (`publishUpload` in manager.ts),
  // never run automatically. Until they do, the stage simply stays pending
  // -- an unpublished archive is the normal resting state, not a warning.
  // "skipped" (the attempt failed) marks the stage with a warning but never
  // blocks the local download/save flow, and can be retried.
  const storageState: StageState =
    storage?.status === "running"
      ? "active"
      : storage?.status === "stored"
        ? "completed"
        : storage?.status === "skipped"
          ? "warning"
          : "pending"

  const storageLogs: LogLine[] = []
  if (storage) {
    storageLogs.push({
      text: "Publishing to Hugging Face Hub — POST /storage (uploading the .corpus archive)…",
      tone: "info",
    })
  }
  switch (storage?.status) {
    case "stored":
      storageLogs.push(
        {
          text: `Stored ${storage.filename ?? "archive"}${
            storage.sizeBytes !== undefined
              ? ` (${formatBytes(storage.sizeBytes)})`
              : ""
          } in ${storage.repoId ?? "the Hub storage repo"}`,
          tone: "success",
        },
        ...(storage.url
          ? [
              {
                text: `Download URL: ${storage.url}`,
                tone: "success",
              } satisfies LogLine,
            ]
          : [])
      )
      break
    case "skipped":
      storageLogs.push({
        text: `Publish failed: ${
          storage.reasons?.[0] ?? "unknown error"
        }. The archive is still downloadable locally — use “Publish to Hugging Face” to retry.`,
        tone: "warning",
      })
      break
  }
  if (!storage && done) {
    storageLogs.push({
      text: "Not published — use “Publish to Hugging Face” in the result panel to push the archive to the Hub.",
      tone: "info",
    })
  }

  return [
    {
      id: "received",
      label: "File received",
      state: "completed",
      logs: [
        {
          text: `File received: ${entry.name} (${formatBytes(entry.size)})`,
          tone: "info",
        },
      ],
    },
    {
      id: "validated",
      label: "File type validated",
      state: sourceFormat
        ? "completed"
        : failedBeforeServer
          ? "failed"
          : "completed",
      logs: [
        // ZIP inspection findings (contents inventory, extraction notes)
        // happen as part of validating what the upload actually is.
        ...(entry.inspection ?? []).map((text): LogLine => ({
          text,
          tone: "info",
        })),
        ...(sourceFormat
          ? [
              {
                text: `File type validated — source format "${sourceFormat}"`,
                tone: "success",
              } satisfies LogLine,
            ]
          : []),
      ],
    },
    {
      id: "upload",
      label: "Uploaded to conversion service",
      state: uploadState,
      logs: uploadLogs,
    },
    {
      id: "queued",
      label: "Queued for conversion",
      state: queuedState,
      logs: jobId
        ? [
            {
              text: `Job ${jobId} created — tracking status over WebSocket`,
              tone: "success",
            },
          ]
        : [],
    },
    {
      id: "converting",
      label: "Converting to .corpus",
      state: convertingState,
      logs: convertingLogs,
    },
    {
      id: "validation",
      label: "Dataset validated",
      state: validationState,
      logs: validationLogs,
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
              tone: "success",
            },
          ]
        : [],
    },
    // Last because it's a manual, post-completion action -- the pipeline is
    // done at "download"; this stage tracks the optional Hub publish the
    // user can trigger (and retry) from the result panel.
    {
      id: "storage",
      label: "Published to Hugging Face",
      state: storageState,
      logs: storageLogs,
    },
  ]
}

/** The stage a failed run stopped at, for plain-language error reporting. */
export const failedStage = (stages: Stage[]): Stage | undefined =>
  stages.find((stage) => stage.state === "failed")
