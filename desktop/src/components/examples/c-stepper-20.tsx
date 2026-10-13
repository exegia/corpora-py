import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

const steps = ["Source", "Options", "Review"] as const
export type ConversionReviewStep = 0 | 1 | 2

/** ReUI stepper-20's connected check rail, used for the actual submission review. */
export function ConversionReviewSteps({
    current,
    reachable,
    onChange,
    disabled
}: {
    current: ConversionReviewStep
    reachable: ConversionReviewStep
    onChange: (step: ConversionReviewStep) => void
    disabled?: boolean
}) {
    return (
        <nav aria-label="New conversion steps">
            <ol className="grid grid-cols-3 gap-2">
                {steps.map((title, index) => {
                    const step = index as ConversionReviewStep
                    const complete = step < current
                    return (
                        <li
                            key={title}
                            className="relative">
                            {step !== 2 && (
                                <span
                                    aria-hidden="true"
                                    className={cn(
                                        "pointer-events-none absolute start-8 end-0 top-4 border-t border-dashed",
                                        complete ? "border-primary/50" : "border-border"
                                    )}
                                />
                            )}
                            <button
                                type="button"
                                onClick={() => onChange(step)}
                                disabled={disabled || step > reachable}
                                aria-current={step === current ? "step" : undefined}
                                className="relative flex min-h-12 items-center gap-2 rounded-lg px-1 text-start text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
                                <span
                                    aria-hidden="true"
                                    className={cn(
                                        "flex size-7 shrink-0 items-center justify-center rounded-full border bg-card text-xs",
                                        complete
                                            ? "border-primary bg-primary text-primary-foreground"
                                            : step === current
                                              ? "border-primary bg-accent text-primary"
                                              : "border-border text-muted-foreground"
                                    )}>
                                    {complete ? (
                                        <Check
                                            className="size-3.5"
                                            strokeWidth={2}
                                        />
                                    ) : (
                                        index + 1
                                    )}
                                </span>
                                <span
                                    className={cn(
                                        "relative bg-card pe-2",
                                        step === current ? "font-semibold text-foreground" : "text-muted-foreground"
                                    )}>
                                    {title}
                                </span>
                            </button>
                        </li>
                    )
                })}
            </ol>
        </nav>
    )
}
