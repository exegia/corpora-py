import { Check, CircleDashed, LoaderCircle, X } from "lucide-react"
import { Badge, type BadgeProps } from "@/components/reui/badge"
import type { ConversionJob } from "@/shared/conversion"

const presentation: Record<ConversionJob["status"], { label: string; variant: BadgeProps["variant"]; icon: typeof Check }> = {
    queued: { label: "Queued", variant: "outline", icon: CircleDashed },
    running: { label: "Running", variant: "primary-light", icon: LoaderCircle },
    succeeded: { label: "Succeeded", variant: "success-light", icon: Check },
    failed: { label: "Failed", variant: "destructive-light", icon: X },
}

export function ConversionJobStatus({ status }: { status: ConversionJob["status"] }) {
    const { label, variant, icon: Icon } = presentation[status]
    return <Badge variant={variant} radius="full"><Icon aria-hidden="true" className={status === "running" ? "motion-safe:animate-spin" : undefined} />{label}</Badge>
}

export function conversionDate(timestamp: number): string {
    return new Date(timestamp * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
}
