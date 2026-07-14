import { useEffect, useRef, useState } from "react"
import { type MetaDescriptor } from "react-router"
import { Card, CardContent } from "~/components/ui/card"
import { Badge } from "~/components/ui/badge"
import { GithubRepoInput } from "~/components/convert/github-repo-input"
import { UploadDropzone } from "~/components/convert/upload-dropzone"
import { FileSummary } from "~/components/convert/file-summary"
import { ProcessingStages } from "~/components/convert/processing-stages"
import { LogConsole, type LogLine, TONE_PREFIX } from "~/components/convert/log-console"
import { CompletedResult, FailedResult } from "~/components/convert/result-actions"
import { deriveStages, deriveView, failedStage, type Stage } from "~/components/convert/state-model"
import type { UploadEntry } from "~/lib/atoms/upload-atom"
import { useUpload } from "~/lib/hooks/use-upload"
import { cue } from "~/lib/cue"
import { extractZipEntry, inspectZip } from "~/lib/uploads/inspect-zip"
import { EXTENSION_TO_FORMAT } from "~/lib/uploads/source-format"
import { cn } from "~/lib/utils"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Convert | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" }
  ]
}

const ACCEPTED_EXTENSIONS = Object.keys(EXTENSION_TO_FORMAT)

// The bottom block of the console carries only the final completion
// message -- the per-stage log lines live inline in the stage timeline
// (see deriveStages).
const buildCompletionLines = (entry: UploadEntry | undefined): LogLine[] => {
  if (!entry) return []
  // A failed validation never blocks download/save (see manager.ts), so the
  // completion block carries the caveat alongside the success message rather
  // than replacing it.
  const validationCaveat: LogLine[] =
    entry.validation?.status === "invalid"
      ? [
        {
          text: "Warning: the corpus failed validation — see the “Dataset validated” step above before shipping this archive.",
          tone: "warning"
        }
      ]
      : []
  switch (entry.status) {
    case "error":
      return [
        {
          text: `Conversion failed: ${entry.error ?? "unknown error"}`,
          tone: "error"
        }
      ]
    case "ready":
      return [
        ...validationCaveat,
        {
          text: `Conversion complete — ${entry.corpusName ?? "archive"} is ready. Use “Save .corpus” to write it to disk.`,
          tone: "success"
        }
      ]
    case "success":
      return [
        ...validationCaveat,
        {
          text: `Conversion complete — ${entry.corpusName ?? "archive"} saved to disk.`,
          tone: "success"
        }
      ]
    default:
      return []
  }
}

const STATUS_TEXT: Record<UploadEntry["status"], string> = {
  uploading: "Uploading file to the conversion service…",
  queued: "Queued — waiting for the conversion worker…",
  converting: "Converting — this can take a while for large documents.",
  validating: "Validating — checking the dataset loads through the .tf → .cfm cycle…",
  ready: "Conversion completed. Archive ready to save.",
  success: "Conversion completed and saved to disk.",
  error: "Conversion failed. See the failed step above."
}

const buildCopyText = (stages: Stage[], completion: LogLine[]): string =>
  [...stages.flatMap((stage) => stage.logs), ...completion]
    .map((line) => `${TONE_PREFIX[line.tone]} ${line.text}`)
    .join("\n")

export default function CorpusConvert() {
  const [currentUploadId, setCurrentUploadId] = useState<string | null>(null)
  const [rejection, setRejection] = useState<string | null>(null)
  const { uploads, uploadFile, deleteUpload, retryUpload, saveUpload } =
    useUpload()

  const entry = currentUploadId ? uploads[currentUploadId] : undefined

  // Play a cue on meaningful status transitions of the tracked upload. A ref
  // keyed by (id, status) makes each transition fire exactly once, even
  // though the atom re-renders this component on every log line. The first
  // time a brand-new upload appears (currentUploadId only ever points at
  // fresh, this-session uploads) its "uploading"/"queued" state stands in for
  // "conversion started".
  const cuedRef = useRef<{ id: string; status: UploadEntry["status"] } | null>(
    null
  )
  useEffect(() => {
    if (!entry) {
      cuedRef.current = null
      return
    }
    const prev = cuedRef.current
    const isNew = prev?.id !== entry.id
    if (!isNew && prev?.status === entry.status) return
    cuedRef.current = { id: entry.id, status: entry.status }

    if (isNew && (entry.status === "uploading" || entry.status === "queued")) {
      cue("upload")
      return
    }
    switch (entry.status) {
      case "ready":
        cue("converted")
        break
      case "success":
        cue("saved")
        break
      case "error":
        cue("error")
        break
    }
  }, [entry?.id, entry?.status])

  const view = deriveView(entry)
  const stages = entry ? deriveStages(entry) : []
  const completionLines = buildCompletionLines(entry)
  const totalLogCount =
    stages.reduce((count, stage) => count + stage.logs.length, 0) +
    completionLines.length

  // A ZIP is a container, not a format -- inspect it client-side to decide
  // what it actually is (see inspect-zip.ts): a Text-Fabric dataset goes up
  // as tf_zip (the existing behavior), a single zipped document is extracted
  // and continues the normal single-file flow, and anything the service
  // can't convert is rejected here with an inline explanation instead of a
  // doomed round-trip.
  // A rejection (unsupported file, un-extractable archive) gets a negative
  // cue. Clearing the message on the next attempt stays a plain setState with
  // no sound.
  const reject = (message: string) => {
    cue("reject")
    setRejection(message)
  }

  const handleFile = async (file: File) => {
    setRejection(null)
    setCurrentUploadId(null)

    if (!file.name.toLowerCase().endsWith(".zip")) {
      setCurrentUploadId(await uploadFile(file))
      return
    }

    const result = await inspectZip(file)
    switch (result.kind) {
      case "unsupported":
        reject(result.message)
        return
      case "tf":
      case "fallback":
        setCurrentUploadId(
          await uploadFile(file, {
            sourceFormat: "tf_zip",
            inspection: result.notes
          })
        )
        return
      case "tei":
        setCurrentUploadId(
          await uploadFile(file, {
            sourceFormat: "tei_zip",
            inspection: result.notes
          })
        )
        return
      case "document": {
        const extracted = await extractZipEntry(file, result.entry)
        if (!extracted) {
          reject(
            `"${result.entry.name}" inside ${file.name} uses a compression method this app can't extract. Upload the document directly instead.`
          )
          return
        }
        setCurrentUploadId(
          await uploadFile(extracted, { inspection: result.notes })
        )
      }
    }
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
              <>
                <GithubRepoInput onFile={(file) => void handleFile(file)} />
                <UploadDropzone
                  extensions={ACCEPTED_EXTENSIONS}
                  className="rounded-xl"
                  hint="Drag and drop, or browse"
                  error={rejection}
                  onFile={(file) => void handleFile(file)}
                  onReject={reject}
                />
              </>
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
                lines={completionLines}
                status={STATUS_TEXT[entry.status]}
                scrollKey={totalLogCount}
                copyText={buildCopyText(stages, completionLines)}
              />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
