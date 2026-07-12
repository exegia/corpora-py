"use client"

import { FileUp, LoaderCircle } from "lucide-react"
import { useRef, useState } from "react"
import { cn } from "~/lib/utils"

interface Upload8Props {
  title?: string
  formats?: string[]
  limit?: string
  action?: string
  className?: string
  accept?: string
  disabled?: boolean
  status?: string
  error?: string | null
  onUpload?: (file: File) => Promise<void> | void
  sample?: { name: string; url: string }
  resultAction?: { label: string; onClick: () => void }
}

export const upload8Demo: Upload8Props = {
  title: "Upload artwork",
  formats: ["PNG", "JPG", "SVG", "WebP"],
  limit: "Up to 10 MB",
  action: "Browse files"
}

export function Upload8({
                          title,
                          formats = [],
                          limit,
                          action = "Browse",
                          className,
                          accept,
                          disabled = false,
                          status,
                          error,
                          onUpload,
                          sample,
                          resultAction
                        }: Upload8Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isLoadingSample, setIsLoadingSample] = useState(false)

  const upload = async (file: File) => {
    await onUpload?.(file)
    if (inputRef.current) inputRef.current.value = ""
  }

  const uploadSample = async () => {
    if (!sample) return
    setIsLoadingSample(true)
    try {
      const response = await fetch(sample.url)
      if (!response.ok)
        throw new Error(`Could not load ${sample.name} (${response.status})`)
      const file = new File([await response.blob()], sample.name, {
        type: "application/zip"
      })
      await upload(file)
    } finally {
      setIsLoadingSample(false)
    }
  }

  return (
    <div
      className={cn(
        "relative flex size-full items-center justify-center p-4",
        className
      )}
    >
      <div
        className="flex w-full max-w-80 flex-col items-center gap-3 rounded-xl border-2 border-dashed border-border bg-card px-5 py-6 text-center shadow-sm">
        <div className="flex size-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <FileUp className="size-4" aria-hidden="true" />
        </div>
        {title && (
          <span className="text-sm font-semibold text-card-foreground">
            {title}
          </span>
        )}
        {formats.length > 0 && (
          <div className="flex flex-wrap items-center justify-center gap-1">
            {formats.map((fmt, idx) => (
              <span
                key={idx}
                className="rounded-full border border-border bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground"
              >
                {fmt}
              </span>
            ))}
          </div>
        )}
        {limit && (
          <span className="text-xs text-muted-foreground">{limit}</span>
        )}
        <button
          type="button"
          disabled={disabled || isLoadingSample}
          onClick={() =>
            sample ? void uploadSample() : inputRef.current?.click()
          }
          className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-semibold text-card-foreground shadow-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoadingSample && (
            <LoaderCircle className="size-3 animate-spin" aria-hidden="true" />
          )}
          {action}
        </button>
        {sample && (
          <button
            type="button"
            disabled={disabled || isLoadingSample}
            onClick={() => inputRef.current?.click()}
            className="text-xs font-medium text-muted-foreground underline-offset-4 hover:text-card-foreground hover:underline disabled:opacity-50"
          >
            Choose another ZIP
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          disabled={disabled}
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
          }}
        />
        {status && (
          <span className="text-xs font-medium text-card-foreground">
            {status}
          </span>
        )}
        {resultAction && (
          <button
            type="button"
            onClick={resultAction.onClick}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
          >
            {resultAction.label}
          </button>
        )}
        {error && (
          <span className="text-xs text-destructive" role="alert">
            {error}
          </span>
        )}
      </div>
    </div>
  )
}
