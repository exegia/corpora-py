import { useEffect, useRef, useState } from "react"
import { type MetaDescriptor } from "react-router"
import { Card, CardContent } from "~/components/ui/card"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import { GithubRepoInput } from "~/components/convert/github-repo-input"
import { UploadDropzone } from "~/components/convert/upload-dropzone"
import { FileSummary } from "~/components/convert/file-summary"
import { PdfReliabilityResult } from "~/components/convert/pdf-reliability-result"
import { ProcessingStages } from "~/components/convert/processing-stages"
import {
  LogConsole,
  type LogLine,
  TONE_PREFIX,
} from "~/components/convert/log-console"
import {
  CompletedResult,
  FailedResult,
} from "~/components/convert/result-actions"
import {
  deriveStages,
  deriveView,
  failedStage,
  type Stage,
} from "~/components/convert/state-model"
import type { UploadEntry } from "~/lib/atoms/upload-atom"
import { useUpload } from "~/lib/hooks/use-upload"
import { cue } from "~/lib/cue"
import { extractZipEntry, inspectZip } from "~/lib/uploads/inspect-zip"
import { EXTENSION_TO_FORMAT } from "~/lib/uploads/source-format"
import { cn } from "~/lib/utils"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Convert | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" },
  ]
}

const ACCEPTED_EXTENSIONS = Object.keys(EXTENSION_TO_FORMAT)

// The bottom block of the console carries only the final completion
// message -- the per-stage log lines live inline in the stage timeline
// (see deriveStages).
const buildCompletionLines = (entry: UploadEntry | undefined): LogLine[] => {
  if (!entry) return []
  // Other formats can retain a validation caveat. PDF source acceptance is
  // enforced before the entry becomes ready (see manager.ts).
  const validationCaveat: LogLine[] =
    entry.validation?.status === "invalid"
      ? [
          {
            text: "Warning: the corpus failed validation — see the “Dataset validated” step above before shipping this archive.",
            tone: "warning",
          },
        ]
      : []
  // The Hub publish is a manual, optional step (see `publishUpload` in
  // manager.ts): once the user triggers it, a stored archive gets its
  // download URL in the completion block and a failed attempt gets a caveat
  // -- neither changes the local success message, and an entry that was
  // never published gets no line at all.
  const storageLines: LogLine[] =
    entry.storage?.status === "stored" && entry.storage.url
      ? [
          {
            text: `Published to Hugging Face — download URL: ${entry.storage.url}`,
            tone: "success",
          },
        ]
      : entry.storage?.status === "skipped"
        ? [
            {
              text: "Warning: the archive was not published to Hugging Face — see the “Published to Hugging Face” step for the reason, then retry.",
              tone: "warning",
            },
          ]
        : []
  switch (entry.status) {
    case "error":
      return [
        {
          text: `Conversion failed: ${entry.error ?? "unknown error"}`,

          description: `${entry.error ?? "unknown error"}`,
          tone: "error",
        },
      ]
    case "ready":
      return [
        ...validationCaveat,
        ...storageLines,
        {
          text: `Conversion complete`,
          description: `${entry.corpusName ?? "archive"} is ready. Use “Download” to write it to disk.`,
          tone: "success",
        },
      ]
    case "success":
      return [
        ...validationCaveat,
        ...storageLines,
        {
          text: `Conversion complete`,
          description: `${entry.corpusName ?? "archive"} saved to disk.`,
          tone: "success",
        },
      ]
    default:
      return []
  }
}

const STATUS_TEXT: Record<UploadEntry["status"], string> = {
  uploading: "Uploading file to the conversion service…",
  queued: "Queued — waiting for the conversion worker…",
  converting: "Converting — this can take a while for large documents.",
  validating: "Validating — checking the converted archive…",
  ready: "Conversion completed. Archive ready to save.",
  success: "Conversion completed and saved to disk.",
  error: "Conversion failed. See the failed step above.",
}

const buildCopyText = (stages: Stage[], completion: LogLine[]): string =>
  [...stages.flatMap((stage) => stage.logs), ...completion]
    .map((line) => `${TONE_PREFIX[line.tone]} ${line.text}`)
    .join("\n")

export default function CorpusConvert() {
  const [currentUploadId, setCurrentUploadId] = useState<string | null>(null)
  const [rejection, setRejection] = useState<string | null>(null)
  const [outputFormat, setOutputFormat] = useState<"corpus" | "cusx">("cusx")
  const {
    uploads,
    uploadFile,
    deleteUpload,
    retryUpload,
    saveUpload,
    publishUpload,
  } = useUpload()

  const entry = currentUploadId ? uploads[currentUploadId] : undefined

  // A refresh must resume the active conversion card as well as its tracker.
  useEffect(() => {
    if (currentUploadId) return
    const active = Object.values(uploads)
      .filter((upload) => ["queued", "converting", "validating"].includes(upload.status))
      .sort((a, b) => (b.uploadedAt ?? 0) - (a.uploadedAt ?? 0))[0]
    if (active) setCurrentUploadId(active.id)
  }, [uploads, currentUploadId])

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
  // A rejection (unsupported file, unextractable archive) gets a negative
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
      setCurrentUploadId(uploadFile(file, { outputFormat }))
      return
    }

    const result = await inspectZip(file)
    switch (result.kind) {
      case "unsupported":
        reject(result.message)
        return
      case "tf":
      case "fallback":
        if (outputFormat === "cusx") {
          reject(
            "Dataset ZIPs use Corpus (.corpus). Choose Corpus before uploading this archive."
          )
          return
        }
        setCurrentUploadId(
          uploadFile(file, {
            sourceFormat: "tf_zip",
            outputFormat,
            inspection: result.notes,
          })
        )
        return
      case "tei":
        if (outputFormat === "cusx") {
          reject(
            "TEI dataset ZIPs use Corpus (.corpus). Choose Corpus before uploading this archive."
          )
          return
        }
        setCurrentUploadId(
          uploadFile(file, {
            sourceFormat: "tei_zip",
            outputFormat,
            inspection: result.notes,
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
          uploadFile(extracted, { outputFormat, inspection: result.notes })
        )
      }
    }
  }

  const handleReset = () => {
    if (currentUploadId) deleteUpload(currentUploadId)
    setCurrentUploadId(null)
    setRejection(null)
  }

  const handleRetry = () => {
    if (!currentUploadId) return
    setCurrentUploadId(retryUpload(currentUploadId) ?? null)
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">
          Convert to{" "}
          <Badge variant="secondary" className="py-1.5 text-xl">
            {outputFormat === "cusx" ? ".cusx" : ".corpus"}
          </Badge>
        </h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          {outputFormat === "cusx"
            ? "Package document text, source hierarchy and available resources as C-USX."
            : "Build a Corpus archive with Text-Fabric and Context-Fabric for corpus readers and graph queries."}
        </p>
        <div
          className="mt-3 flex flex-wrap gap-2"
          role="group"
          aria-label="Conversion output"
        >
          <Button
            variant={outputFormat === "corpus" ? "default" : "outline"}
            aria-pressed={outputFormat === "corpus"}
            disabled={view !== "empty"}
            onClick={() => {
              setOutputFormat("corpus")
              setRejection(null)
            }}
          >
            Corpus (.corpus)
          </Button>
          <Button
            variant={outputFormat === "cusx" ? "default" : "outline"}
            aria-pressed={outputFormat === "cusx"}
            disabled={view !== "empty"}
            onClick={() => {
              setOutputFormat("cusx")
              setRejection(null)
            }}
          >
            C-USX (.cusx)
          </Button>
        </div>
      </div>

      {view === "empty" && (
        <div className="rounded-xl border border-border bg-muted/30 p-4 text-sm">
          <p className="font-medium">PDFs use forced OCR on every page</p>
          <p className="mt-1 text-muted-foreground">
            Docling 2.137.0 converts the PDF and records its snapshot and hashes.
            Independent visual OCR then compares every original PDF page with the result.
            The agreement estimate applies these thresholds: below 50% is a loss,
            50–90% needs review and manual editing, and above 90% passes.
          </p>
          <p className="mt-2 text-muted-foreground">
            Scores include word order and Hebrew/Greek marks. Review mismatches
            before using the result; agreement between OCR engines can share errors.
          </p>
        </div>
      )}

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
                {outputFormat === "corpus" && (
                  <GithubRepoInput onFile={(file) => void handleFile(file)} />
                )}
                <h2 className="mt-4 ml-3 text-xl font-medium">
                  Upload from your computer
                </h2>
                <UploadDropzone
                  extensions={ACCEPTED_EXTENSIONS}
                  className="rounded-2xl"
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
                  {entry.sourceFormat === "pdf" && entry.validation?.sourceReliability && (
                    <PdfReliabilityResult report={entry.validation.sourceReliability} />
                  )}
                  {view === "completed" && entry.corpusName && (
                    <CompletedResult
                      displayName={entry.displayName}
                      corpusName={entry.corpusName}
                      corpusSize={entry.corpusSize}
                      saved={entry.status === "success"}
                      storage={entry.storage}
                      onPublish={() => void publishUpload(entry.id)}
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
                title="Logs"
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
