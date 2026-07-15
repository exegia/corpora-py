"use client"

import { CircleAlert } from "lucide-react"
import { useFileUpload } from "~/lib/hooks/use-file-upload"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Button } from "~/components/ui/button"
import { cn } from "~/lib/utils"
import GlassFolder from "../glass-folder"

interface UploadDropzoneProps {
  title?: string
  /** Accepted extensions, e.g. [".zip", ".pdf"]. Used for both validation and display. */
  extensions: string[]
  hint?: string
  disabled?: boolean
  /** Inline rejection message (unsupported file); cleared by the parent on the next attempt. */
  error?: string | null
  onFile: (file: File) => void
  onReject: (message: string) => void
  className?: string
}

/**
 * Initial empty upload state: the drag-and-drop box, shown only while no
 * file has been accepted. Validates the extension as soon as a file is
 * dropped or picked -- an unsupported file keeps this view and reports an
 * inline error through `onReject`, so the user can retry without a reload.
 */
export function UploadDropzone({
  title = "Upload your file",
  extensions,
  hint,
  disabled = false,
  error,
  onFile,
  onReject,
  className,
}: UploadDropzoneProps) {
  const accept = extensions.join(",")

  const [
    { isDragging },
    {
      handleDragEnter,
      handleDragLeave,
      handleDragOver,
      handleDrop,
      openFileDialog,
      getInputProps,
    },
  ] = useFileUpload({
    accept,
    multiple: false,
    onFilesAdded: (added) => {
      const file = added[0]?.file
      if (file instanceof File) onFile(file)
    },
    onError: (errors) => {
      if (errors[0]) onReject(errors[0])
    },
  })

  return (
    <div
      className={cn(
        "flex w-full cursor-pointer flex-col gap-3 bg-neutral-100 dark:bg-neutral-800",
        className
      )}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <div
        className={cn(
          "group flex min-h-72 w-full flex-col items-center justify-center gap-3 overflow-clip rounded-xl border-2" +
            " border-dashed px-5 py-6 text-center transition-colors",
          isDragging
            ? "border-primary bg-primary/5"
            : "border-border bg-background/10",
          error && !isDragging && "border-destructive/50"
        )}
      >
        <GlassFolder
          className="scale-75 transform"
          open={false}
          isHovered={isDragging}
        />
        <span className="text-lg font-semibold text-card-foreground">
          {isDragging ? "Drop to upload" : title}
        </span>
        <div className="flex flex-wrap items-center justify-center gap-2">
          {extensions.map((extension) => (
            <span
              key={extension}
              className="mb-4 rounded-full border-2 border-border bg-neutral-200 px-2 py-0.5 font-mono text-xs text-muted-foreground dark:bg-neutral-900"
            >
              {extension}
            </span>
          ))}
        </div>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
        <Button
          type="button"
          className="cursor-pointer"
          disabled={disabled}
          onClick={openFileDialog}
          data-cuelume-press
          data-cuelume-release
        >
          Browse files
        </Button>
        <input
          {...getInputProps({ disabled })}
          className="sr-only"
          aria-label="Upload file"
        />
      </div>

      {error && (
        <Alert variant="destructive" role="alert">
          <CircleAlert className="size-4" aria-hidden="true" />
          <AlertTitle>File type not supported</AlertTitle>
          <AlertDescription>
            <p>{error}</p>
            <p className="mt-1">
              Accepted file types: {extensions.join(", ")}. Drop another file or
              browse to try again.
            </p>
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
