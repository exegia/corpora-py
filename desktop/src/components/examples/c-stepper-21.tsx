import { Check, Minus, X } from "lucide-react"
import { Badge } from "@/components/reui/badge"
import { cn } from "@/lib/utils"
import type { ConversionJob } from "@/shared/conversion"

type StepStatus = ConversionJob["steps"][number]["status"]
const labels: Record<StepStatus, string> = {
    pending: "Pending",
    running: "In progress",
    completed: "Completed",
    failed: "Failed",
    skipped: "Skipped"
}

/** The dashed track and indeterminate arc from ReUI stepper-21, not a percentage. */
export function ConversionStepIndicator({ status }: { status: StepStatus }) {
    if (status === "completed" || status === "failed" || status === "skipped") {
        const Icon = status === "completed" ? Check : status === "failed" ? X : Minus
        return (
            <span
                aria-hidden="true"
                className={cn(
                    "flex size-5 shrink-0 items-center justify-center rounded-full border",
                    status === "completed"
                        ? "border-success/30 bg-success/10 text-success-foreground"
                        : status === "failed"
                          ? "border-destructive/30 bg-destructive/10 text-destructive-foreground"
                          : "border-border text-muted-foreground"
                )}>
                <Icon
                    className="size-3"
                    strokeWidth={2}
                />
            </span>
        )
    }
    return (
        <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            fill="none"
            strokeWidth="1.6"
            className="size-5 shrink-0">
            <circle
                cx="8"
                cy="8"
                r="7"
                strokeDasharray="3 1"
                className="stroke-muted-foreground/40"
            />
            {status === "running" && (
                <circle
                    cx="8"
                    cy="8"
                    r="7"
                    strokeDasharray="17 27"
                    strokeDashoffset="14.4"
                    className="origin-center stroke-primary motion-safe:animate-spin"
                />
            )}
        </svg>
    )
}

export function ConversionProgressSteps({
    steps,
    selectedStage,
    onSelectStage
}: {
    steps: ConversionJob["steps"]
    selectedStage: string | null
    onSelectStage: (stage: string | null) => void
}) {
    const completed = steps.filter((step) => step.status === "completed").length
    const skipped = steps.filter((step) => step.status === "skipped").length
    return (
        <section
            aria-label="Conversion pipeline"
            className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">Pipeline</h3>
                <p className="text-xs tabular-nums text-muted-foreground">
                    {steps.length
                        ? `${completed} of ${steps.length} stages completed${skipped ? ` · ${skipped} skipped` : ""}`
                        : "Waiting for reported stages"}
                </p>
            </div>
            {steps.length ? (
                <ol className="grid gap-1 sm:grid-cols-2 xl:grid-cols-3">
                    {steps.map((step) => (
                        <li key={step.id}>
                            <button
                                type="button"
                                aria-pressed={selectedStage === step.id}
                                onClick={() => onSelectStage(selectedStage === step.id ? null : step.id)}
                                className={cn(
                                    "flex min-h-12 w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-start outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                    selectedStage === step.id
                                        ? "border-primary/40 bg-accent"
                                        : "border-border bg-card hover:bg-muted/50"
                                )}>
                                <ConversionStepIndicator status={step.status} />
                                <span className="flex min-w-0 flex-1 flex-col gap-1">
                                    <span className="text-xs font-medium">{step.title}</span>
                                    <span className="text-xs text-muted-foreground">{labels[step.status]}</span>
                                </span>
                                {step.status === "running" && (
                                    <Badge
                                        variant="primary-light"
                                        size="xs">
                                        Active
                                    </Badge>
                                )}
                            </button>
                        </li>
                    ))}
                </ol>
            ) : (
                <p className="text-sm text-muted-foreground">
                    Stages will appear when the backend reports them. No progress estimate is available.
                </p>
            )}
            <p className="text-xs text-muted-foreground">
                Select a stage to filter its logs. Stage counts are not a time estimate.
            </p>
        </section>
    )
}
