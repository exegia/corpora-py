import { AlertTriangle, ArrowLeft, Check, Circle, Loader2, RefreshCw } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Button } from "~/components/ui/button"
import { filenameToId } from "~/lib/corpus-detail"
import { cn } from "~/lib/utils"
import { LOAD_STEPS, type LoadStepId } from "./corpus-load"

/**
 * The load phase's progress card: one row per {@link LOAD_STEPS} step. Steps
 * before the active one render as done, the active one spins, later ones wait.
 * On failure the active step gets an error mark and a retry/back footer.
 */

export function LoadingProgress({
  filename,
  step,
  error,
  onRetry,
  onBack,
}: {
  filename: string
  /** The step currently running (all earlier steps are done). */
  step: LoadStepId
  /** When set, the active step failed with this message. */
  error?: string
  onRetry: () => void
  onBack: () => void
}) {
  const activeIndex = LOAD_STEPS.findIndex((s) => s.id === step)

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Loading{" "}
        <span className="font-medium text-foreground">
          {filenameToId(filename)}
        </span>{" "}
        into the MCP server — a large corpus can take a moment on first load.
      </p>

      <ol className="flex flex-col gap-1" aria-label="Loading steps">
        {LOAD_STEPS.map((s, index) => {
          const done = index < activeIndex
          const active = index === activeIndex
          const failed = active && error != null
          return (
            <li
              key={s.id}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm",
                active && !failed && "bg-muted/50 font-medium",
                failed && "bg-destructive/10 font-medium text-destructive",
                !done && !active && "text-muted-foreground"
              )}
            >
              {failed ? (
                <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
              ) : done ? (
                <Check
                  className="size-4 shrink-0 text-green-600"
                  aria-hidden="true"
                />
              ) : active ? (
                <Loader2
                  className="size-4 shrink-0 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              ) : (
                <Circle
                  className="size-3.5 shrink-0 opacity-40"
                  aria-hidden="true"
                />
              )}
              {s.label}
            </li>
          )
        })}
      </ol>

      {error != null && (
        <>
          <Alert variant="destructive" role="alert">
            <AlertTriangle className="size-4" aria-hidden="true" />
            <AlertTitle>Couldn’t load the corpus</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <div className="flex gap-2">
            <Button
              onClick={onRetry}
              className="gap-1.5"
              data-cuelume-press
              data-cuelume-release
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              Try again
            </Button>
            <Button
              variant="outline"
              onClick={onBack}
              className="gap-1.5"
              data-cuelume-press
              data-cuelume-release
            >
              <ArrowLeft className="size-4" aria-hidden="true" />
              Pick another corpus
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
