"use client"

import { CircleAlert, CircleCheck, LoaderCircle, RefreshCw, X } from "lucide-react"
import type { UploadEntry, UploadStatus } from "~/lib/atoms/upload-atom"
import { formatBytes } from "~/lib/hooks/use-file-upload"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import { cn } from "~/lib/utils"
import { fileExtension, FileTypeIcon } from "./file-icon"

const STATUS_META: Record<
  UploadStatus,
  { label: string; className: string; busy?: boolean; failed?: boolean }
> = {
  uploading: { label: "Uploading", className: "text-blue-600 dark:text-blue-400", busy: true },
  queued: { label: "Queued", className: "text-blue-600 dark:text-blue-400", busy: true },
  converting: { label: "Converting", className: "text-blue-600 dark:text-blue-400", busy: true },
  validating: { label: "Validating", className: "text-blue-600 dark:text-blue-400", busy: true },
  ready: { label: "Completed", className: "text-emerald-600 dark:text-emerald-400" },
  success: { label: "Saved", className: "text-emerald-600 dark:text-emerald-400" },
  error: { label: "Failed", className: "text-destructive", failed: true }
}

const formatDate = (timestamp: number | undefined): string | null => {
  if (!timestamp) return null
  return new Date(timestamp).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  })
}

interface FileSummaryProps {
  entry: UploadEntry
  onRemove: () => void
  onReplace: () => void
  className?: string
}

/**
 * Selected-file summary panel: replaces the drag-and-drop box once a valid
 * file is accepted. Shows only metadata the browser or the conversion
 * service actually reported -- rows with no reliable value are omitted.
 */
export function FileSummary({ entry, onRemove, onReplace, className }: FileSummaryProps) {
  const status = STATUS_META[entry.status]
  const extension = fileExtension(entry.name)

  const metadata: Array<[string, string | null]> = [
    ["Size", entry.size ? formatBytes(entry.size) : null],
    ["Type", entry.type || (extension ? `.${extension}` : null)],
    ["Source format", entry.sourceFormat ?? null],
    ["Last modified", formatDate(entry.lastModified)],
    ["Uploaded", formatDate(entry.uploadedAt)]
  ]

  return (
    <div
      className={cn(
        "flex w-full flex-col gap-4 rounded-lg border-2 border-border bg-background p-5 shadow-sm",
        "animate-in duration-300 fade-in slide-in-from-bottom-2 motion-reduce:animate-none",
        className
      )}
    >
      <div className="flex items-start gap-3">
        <FileTypeIcon filename={entry.name} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-card-foreground" title={entry.name}>
            {entry.name}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {extension && (
              <Badge variant="secondary" className="font-mono uppercase">
                {extension}
              </Badge>
            )}
            <span
              className={cn("inline-flex items-center gap-1 text-xs font-medium", status.className)}
              role="status"
            >
              {status.busy ? (
                <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : status.failed ? (
                <CircleAlert className="size-3.5" aria-hidden="true" />
              ) : (
                <CircleCheck className="size-3.5" aria-hidden="true" />
              )}
              {status.label}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground"
            onClick={onReplace}
            title="Replace file"
            aria-label="Replace file"
            data-cuelume-press
            data-cuelume-release
          >
            <RefreshCw className="size-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground"
            onClick={onRemove}
            title="Remove file"
            aria-label="Remove file"
            data-cuelume-press
            data-cuelume-release
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-border pt-3 text-sm sm:grid-cols-3">
        {metadata
          .filter((row): row is [string, string] => row[1] !== null)
          .map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="truncate font-medium text-card-foreground" title={value}>
                {value}
              </dd>
            </div>
          ))}
      </dl>
    </div>
  )
}
