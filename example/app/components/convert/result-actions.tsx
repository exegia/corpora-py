"use client"

import { CircleAlert, CircleCheck, CloudUpload, Download, RefreshCw, Undo2 } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Button } from "~/components/ui/button"
import { formatBytes } from "~/lib/hooks/use-file-upload"
import { cn } from "~/lib/utils"
import { FileTypeIcon } from "./file-icon"

interface CompletedResultProps {
  corpusName: string
  corpusSize?: number
  /** Already saved to disk ("success") vs. downloaded and awaiting save ("ready"). */
  saved: boolean
  /**
   * Hugging Face Hub download URL of the published archive, when the
   * post-conversion publish succeeded (see `StorageOutcome` in
   * upload-atom.ts). Absent when publishing was skipped or never ran.
   */
  storageUrl?: string
  /** The Hub repo the archive was stored in, shown next to the link. */
  storageRepoId?: string
  onSave: () => void
  onReset: () => void
  className?: string
}

/** Completion state: success message, output file, and next actions. */
export function CompletedResult({
                                  corpusName,
                                  corpusSize,
                                  saved,
                                  storageUrl,
                                  storageRepoId,
                                  onSave,
                                  onReset,
                                  className
                                }: CompletedResultProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 animate-in duration-300 fade-in slide-in-from-bottom-2 motion-reduce:animate-none",
        className
      )}
    >
      <Alert role="status" className="bg-background border-2 p-3">
        <CircleCheck className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
        <AlertTitle>Conversion completed</AlertTitle>
        <AlertDescription>
          {saved
            ? "The archive was saved to disk."
            : "The archive is ready to save to disk."}
        </AlertDescription>
      </Alert>

      <div className="flex items-center gap-3 rounded-lg border-border border-2 bg-background p-3">
        <FileTypeIcon filename={corpusName} className="size-10 rounded-lg" iconClassName="size-5" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={corpusName}>
            {corpusName}
          </p>
          {corpusSize !== undefined && (
            <p className="text-xs text-muted-foreground">{formatBytes(corpusSize)}</p>
          )}
        </div>
      </div>

      {storageUrl && (
        <div className="flex items-center gap-3 rounded-lg border-border border-2 bg-background p-3">
          <CloudUpload
            className="size-5 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              Published to Hugging Face
              {storageRepoId ? ` — ${storageRepoId}` : ""}
            </p>
            <a
              href={storageUrl}
              target="_blank"
              rel="noreferrer"
              className="block truncate text-xs text-blue-600 underline underline-offset-2 dark:text-blue-400"
              title={storageUrl}
            >
              {storageUrl}
            </a>
          </div>
        </div>
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
                               className
                             }: FailedResultProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 animate-in duration-300 fade-in slide-in-from-bottom-2 motion-reduce:animate-none",
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
