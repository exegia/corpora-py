"use client"

import { CircleAlert, LoaderCircle } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Button } from "~/components/ui/button"
import { Input } from "~/components/ui/input"
import { useGithubRepoImport } from "~/lib/hooks/use-github-repo-import"
import { cn } from "~/lib/utils"
import { GithubIcon } from "~/components/icons/icon-github"

interface GithubRepoInputProps {
  disabled?: boolean
  /** Receives the repo zipball as a File; routed like a dropped ZIP. */
  onFile: (file: File) => void
  className?: string
}

export function GithubRepoInput({
                                  disabled = false,
                                  onFile,
                                  className
                                }: GithubRepoInputProps) {
  const { url, setUrl, phase, busy, importRepository } = useGithubRepoImport({
    onFile
  })

  return (
    <div className={cn("flex w-full flex-col gap-3", className)}>
      <form
        className="group flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy) void importRepository()
        }}
      >
        <div
          className="relative flex flex-1 items-stretch overflow-hidden rounded-full bg-background pr-2 outline-2 outline-transparent focus-within:outline-input">
          <div className="pointer-events-none flex flex-1 items-center gap-1 border-r border-border/50 bg-muted px-2">
            <GithubIcon
              className="h-5 w-5 fill-foreground"
              aria-hidden="true"
            />
            <span className="text-sm text-muted-foreground">
              https://github.com
            </span>
          </div>

          <Input
            type="url"
            value={url}
            placeholder="@owner/repository"
            aria-label="GitHub repository URL"
            aria-invalid={phase.kind === "error" || undefined}
            disabled={disabled || busy}
            className={cn(
              "border-none bg-transparent! focus:ring-0! focus:outline-none",
              className
            )}
            onChange={(event) => setUrl(event.target.value)}
          />
        </div>
        <Button
          type="submit"
          size="sm"
          className="cursor-pointer rounded-full"
          disabled={disabled || busy || !url.trim()}
        >
          {busy && (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          )}
          Import
        </Button>
      </form>

      {phase.kind === "checking" && (
        <p className="text-xs text-muted-foreground" role="status">
          {phase.message}
        </p>
      )}

      {phase.kind === "error" && (
        <Alert variant="destructive" role="alert">
          <CircleAlert className="size-4" aria-hidden="true" />
          <AlertTitle>Can't import repository</AlertTitle>
          <AlertDescription>
            <p>{phase.message}</p>
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
