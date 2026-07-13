"use client"

import {
  Circle,
  CircleCheck,
  CircleX,
  LoaderCircle,
  TriangleAlert
} from "lucide-react"
import { cn } from "~/lib/utils"
import type { Stage, StageState } from "./state-model"

const STATE_META: Record<
  StageState,
  { label: string; icon: typeof Circle; className: string }
> = {
  pending: { label: "Pending", icon: Circle, className: "text-muted-foreground/50" },
  active: { label: "In progress", icon: LoaderCircle, className: "text-blue-600 dark:text-blue-400" },
  completed: { label: "Completed", icon: CircleCheck, className: "text-emerald-600 dark:text-emerald-400" },
  warning: { label: "Warning", icon: TriangleAlert, className: "text-amber-600 dark:text-amber-400" },
  failed: { label: "Failed", icon: CircleX, className: "text-destructive" }
}

/**
 * Stage-by-stage pipeline view. Completed stages stay visible; each state
 * is communicated with an icon *and* a text label (never color alone).
 * Motion is limited to the active stage's spinner and a short fade when a
 * stage changes state.
 */
export function ProcessingStages({
                                   stages,
                                   className
                                 }: {
  stages: Stage[]
  className?: string
}) {
  return (
    <ol className={cn("flex flex-col", className)} aria-label="Processing stages">
      {stages.map((stage, index) => {
        const meta = STATE_META[stage.state]
        const Icon = meta.icon
        const isLast = index === stages.length - 1
        return (
          <li key={stage.id} className="relative flex gap-3 pb-4 last:pb-0">
            {!isLast && (
              <span
                className={cn(
                  "absolute top-5 left-[9px] h-[calc(100%-1.25rem)] w-px",
                  stage.state === "completed" || stage.state === "warning"
                    ? "bg-emerald-600/40 dark:bg-emerald-400/40"
                    : "bg-border"
                )}
                aria-hidden="true"
              />
            )}
            <Icon
              className={cn(
                "relative z-10 mt-0.5 size-[18px] shrink-0 bg-inherit",
                meta.className,
                stage.state === "active" && "animate-spin motion-reduce:animate-none"
              )}
              aria-hidden="true"
            />
            <div
              className={cn(
                "min-w-0 flex-1 transition-opacity duration-300 motion-reduce:transition-none",
                stage.state === "pending" && "opacity-50"
              )}
            >
              <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
                <span className="font-medium">{stage.label}</span>
                <span className={cn("text-xs", meta.className)}>{meta.label}</span>
              </p>
              {stage.detail && (
                <p className="mt-0.5 truncate text-xs text-muted-foreground" title={stage.detail}>
                  {stage.detail}
                </p>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
