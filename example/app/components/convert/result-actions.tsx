"use client"

import { CircleAlert, CircleCheck, Download, LoaderCircle, RefreshCw, Undo2 } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { HuggingFaceIcon } from "~/components/icons/icon-hugging-face"
import { Button } from "~/components/ui/button"
import type { StorageOutcome } from "~/lib/atoms/upload-atom"
import { useCapabilities } from "~/lib/capabilities"
import { formatBytes } from "~/lib/hooks/use-file-upload"
import { cn } from "~/lib/utils"
import { FileTypeIcon } from "./file-icon"

interface CompletedResultProps {
  corpusName: string
  corpusSize?: number
  /** Already saved to disk ("success") vs. downloaded and awaiting save ("ready"). */
  saved: boolean
  /**
   * Outcome of the manual Hugging Face Hub publish (see `StorageOutcome`
   * in upload-atom.ts). Absent until the user clicks "Publish to Hugging
   * Face" -- publishing never happens automatically.
   */
  storage?: StorageOutcome
  /** Starts (or retries) the manual Hub publish -- see `publishUpload`. */
  onPublish: () => void
  onSave: () => void
  onReset: () => void
  className?: string
}

/** Completion state: success message, output file, and next actions. */
export function CompletedResult({
  corpusName,
  corpusSize,
  saved,
  storage,
  onPublish,
  onSave,
  onReset,
  className,
}: CompletedResultProps) {
  const publishing = storage?.status === "running"
  const published = storage?.status === "stored"
  // A read-only deployment (the public demo) refuses every Hub write, so the
  // publish button would 403 no matter what -- don't offer it. An
  // already-published archive still renders its link below.
  const capabilities = useCapabilities()
  const canPublish = capabilities?.hubWritable === true
  return (
    <div
      className={cn(
        "flex animate-in flex-col gap-3 duration-300 fade-in slide-in-from-bottom-2 motion-reduce:animate-none",
        className
      )}
    >
      <Alert role="status" className="border-2 bg-background p-3">
        <CircleCheck
          className="size-4 text-emerald-600 dark:text-emerald-400"
          aria-hidden="true"
        />
        <AlertTitle>Conversion completed</AlertTitle>
        <AlertDescription>
          {saved
            ? "The archive was saved to disk."
            : "The archive is ready to save to disk."}
        </AlertDescription>
      </Alert>

      <div className="flex items-center gap-3 rounded-lg border-2 border-border bg-background p-3">
        <FileTypeIcon
          filename={corpusName}
          className="size-10 rounded-lg"
          iconClassName="size-5"
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={corpusName}>
            {corpusName}
          </p>
          {corpusSize !== undefined && (
            <p className="text-xs text-muted-foreground">
              {formatBytes(corpusSize)}
            </p>
          )}
        </div>
      </div>

      {published && storage?.url && (
        <div className="flex items-center gap-3 rounded-lg border-2 border-border bg-background p-3">
          <HuggingFaceIcon className="size-6" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              Published to Hugging Face
              {storage.repoId ? ` — ${storage.repoId}` : ""}
            </p>
            <a
              href={storage.url}
              target="_blank"
              rel="noreferrer"
              className="block truncate text-xs text-blue-600 underline underline-offset-2 dark:text-blue-400"
              title={storage.url}
            >
              {storage.url}
            </a>
          </div>
        </div>
      )}

      {storage?.status === "skipped" && (
        <Alert role="alert" className="border-2 bg-background p-3">
          <CircleAlert
            className="size-4 text-amber-600 dark:text-amber-400"
            aria-hidden="true"
          />
          <AlertTitle>Publish to Hugging Face failed</AlertTitle>
          <AlertDescription>
            {storage.reasons?.[0] ?? "Unknown error."} The archive is still
            available locally — you can retry the publish.
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          onClick={onSave}
          className="gap-1.5"
          data-cuelume-press
          data-cuelume-release
        >
          <Download className="size-4" aria-hidden="true" />
          {saved ? "Saved" : "Download"}
        </Button>
        {!published && canPublish && (
          <Button
            variant="outline"
            onClick={onPublish}
            disabled={publishing}
            className="gap-2"
            data-cuelume-press
            data-cuelume-release
          >
            {publishing ? (
              <LoaderCircle
                className="size-4 animate-spin"
                aria-hidden="true"
              />
            ) : (
              <HuggingFaceIcon className="size-4" />
            )}
            {publishing
              ? "Publishing…"
              : storage?.status === "skipped"
                ? "Retry publish"
                : "Publish to Hugging Face"}
          </Button>
        )}
        <Button
          variant="outline"
          onClick={onReset}
          className="gap-1.5"
          data-cuelume-press
          data-cuelume-release
        >
          <Undo2 className="size-4" aria-hidden="true" />
          Convert another file
        </Button>
      </div>
    </div>
  )
}

interface FailedResultProps {
  /** Plain-language description of what went wrong. */
  error: string
  /** Label of the pipeline stage that failed, when known. */
  stageLabel?: string
  onRetry: () => void
  onReplace: () => void
  className?: string
}

/** Failure state: names the failed stage, explains the error, offers recovery. */
export function FailedResult({
  error,
  stageLabel,
  onRetry,
  onReplace,
  className,
}: FailedResultProps) {
  return (
    <div
      className={cn(
        "flex animate-in flex-col gap-3 duration-300 fade-in slide-in-from-bottom-2 motion-reduce:animate-none",
        className
      )}
    >
      <Alert variant="destructive" role="alert">
        <CircleAlert className="size-4" aria-hidden="true" />
        <AlertTitle>
          {stageLabel ? `Failed at: ${stageLabel}` : "Conversion failed"}
        </AlertTitle>
        <AlertDescription>
          <p>{error}</p>
          <p className="mt-1">
            You can retry the same file, or replace it with a different one.
            Completed steps and the log above are preserved.
          </p>
        </AlertDescription>
      </Alert>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          onClick={onRetry}
          className="gap-1.5"
          data-cuelume-press
          data-cuelume-release
        >
          <RefreshCw className="size-4" aria-hidden="true" />
          Retry
        </Button>
        <Button
          variant="outline"
          onClick={onReplace}
          className="gap-1.5"
          data-cuelume-press
          data-cuelume-release
        >
          Replace file
        </Button>
      </div>
    </div>
  )
}
