import { useState } from "react"
import { type MetaDescriptor } from "react-router"
import { Card, CardContent } from "~/components/ui/card"
import { Badge } from "~/components/ui/badge"
import { UploadDropzone } from "~/components/convert/upload-dropzone"
import { FileSummary } from "~/components/convert/file-summary"
import { ProcessingStages } from "~/components/convert/processing-stages"
import { LogConsole, type LogLine } from "~/components/convert/log-console"
import { CompletedResult, FailedResult } from "~/components/convert/result-actions"
import {
  deriveStages,
  deriveView,
  failedStage
} from "~/components/convert/state-model"
import type { UploadEntry } from "~/lib/atoms/upload-atom"
import { formatBytes } from "~/lib/hooks/use-file-upload"
import { useUpload } from "~/lib/hooks/use-upload"
import { EXTENSION_TO_FORMAT } from "~/lib/uploads/source-format"
import { cn } from "~/lib/utils"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Convert | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" }
  ]
}

const ACCEPTED_EXTENSIONS = Object.keys(EXTENSION_TO_FORMAT)

const WARNING_PATTERN = /\bwarn(ing)?\b/i
const ERROR_PATTERN = /\b(error|fail(ed|ure)?)\b/i

// Every line reflects a real event from the tracked entry -- client-side
// validation, the POST round-trip, the server's own coarse checkpoints
// (entry.logs, pushed over /convert/{id}/ws), and the download/save steps.
const buildLogLines = (entry: UploadEntry | undefined): LogLine[] => {
  if (!entry) return []
  const lines: LogLine[] = [
    {
      text: `File received: ${entry.name} (${formatBytes(entry.size)})`,
      tone: "info"
    }
  ]
  if (entry.sourceFormat) {
    lines.push({
      text: `File type validated — source format "${entry.sourceFormat}"`,
      tone: "success"
    })
  }
  lines.push({ text: "Uploading to POST /convert…", tone: "info" })
  if (entry.jobId) {
    lines.push({
      text: `Job ${entry.jobId} created — tracking status over WebSocket`,
      tone: "success"
    })
  }
  for (const line of entry.logs ?? []) {
    lines.push({
      text: line,
      tone: WARNING_PATTERN.test(line)
        ? "warning"
        : ERROR_PATTERN.test(line)
          ? "error"
          : "info"
    })
  }
  if (entry.error) {
    lines.push({ text: `Error: ${entry.error}`, tone: "error" })
    lines.push({
      text: entry.jobId
        ? "Suggested action: retry the conversion, or replace the file."
        : "Suggested action: check that the conversion API is running, then retry.",
      tone: "info"
    })
  }
  if (entry.status === "ready" || entry.status === "success") {
    lines.push({
      text: `Downloaded ${entry.corpusName ?? "archive"}${
        entry.corpusSize !== undefined ? ` (${formatBytes(entry.corpusSize)})` : ""
      }`,
      tone: "success"
    })
    lines.push({
      text:
        entry.status === "success"
          ? "Saved to disk. Conversion complete."
          : "Ready to save. Use “Save .corpus” to write it to disk.",
      tone: "success"
    })
  }
  return lines
}

const STATUS_TEXT: Record<UploadEntry["status"], string> = {
  uploading: "Uploading file to the conversion service…",
  queued: "Queued — waiting for the conversion worker…",
  converting: "Converting — this can take a while for large documents.",
  ready: "Conversion completed. Archive ready to save.",
  success: "Conversion completed and saved to disk.",
  error: "Conversion failed. See the log above for details."
}

export default function CorpusConvert() {
  const [currentUploadId, setCurrentUploadId] = useState<string | null>(null)
  const [rejection, setRejection] = useState<string | null>(null)
  const { uploads, uploadFile, deleteUpload, retryUpload, saveUpload } =
    useUpload()

  const entry = currentUploadId ? uploads[currentUploadId] : undefined
  const view = deriveView(entry)
  const stages = entry ? deriveStages(entry) : []

  const handleFile = async (file: File) => {
    setRejection(null)
    setCurrentUploadId(null)
    setCurrentUploadId(await uploadFile(file))
  }

  const handleReset = () => {
    if (currentUploadId) deleteUpload(currentUploadId)
    setCurrentUploadId(null)
    setRejection(null)
  }

  const handleRetry = async () => {
    if (!currentUploadId) return
    const retried = retryUpload(currentUploadId)
    if (retried) setCurrentUploadId(await retried)
    else setCurrentUploadId(null)
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">
          Convert to{" "}
          <Badge variant="secondary" className="py-1.5 text-xl">
            .corpus
          </Badge>
        </h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Import a source document and package it as a Context-Fabric{" "}
          <code>.corpus</code> archive.
        </p>
      </div>

      <Card>
        <CardContent
          className={cn(
            "grid grid-cols-1 items-start gap-6",
            view !== "empty" && "lg:grid-cols-2"
          )}
        >
          <div className="flex flex-col gap-4">
            {view === "empty" ? (
              <UploadDropzone
                extensions={ACCEPTED_EXTENSIONS}
                hint="Drag and drop, or browse"
                error={rejection}
                onFile={(file) => void handleFile(file)}
                onReject={setRejection}
              />
            ) : (
              entry && (
                <>
                  <FileSummary
                    entry={entry}
                    onRemove={handleReset}
                    onReplace={handleReset}
                  />
                  {view === "completed" && entry.corpusName && (
                    <CompletedResult
                      corpusName={entry.corpusName}
                      corpusSize={entry.corpusSize}
                      saved={entry.status === "success"}
                      onSave={() => void saveUpload(entry.id)}
                      onReset={handleReset}
                    />
                  )}
                  {view === "failed" && (
                    <FailedResult
                      error={entry.error ?? "Something went wrong."}
                      stageLabel={failedStage(stages)?.label}
                      onRetry={() => void handleRetry()}
                      onReplace={handleReset}
                    />
                  )}
                </>
              )
            )}
          </div>

          {view !== "empty" && entry && (
            <div className="animate-in duration-500 fade-in slide-in-from-bottom-3 motion-reduce:animate-none">
              <LogConsole
                title="Conversion console"
                header={<ProcessingStages stages={stages} />}
                lines={buildLogLines(entry)}
                status={STATUS_TEXT[entry.status]}
              />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
