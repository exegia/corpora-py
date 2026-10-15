import { ConversionJobs } from "@/components/conversion-jobs"
import type { ConversionJob, ConversionJobsController } from "@/shared/conversion"
import type { SidecarStatus } from "@/shared/rpc"

export interface JobTabProps {
    backend: SidecarStatus
    conversions: ConversionJobsController
    onOpenJob?: (job: ConversionJob) => void
}

export function JobTab({ backend, conversions, onOpenJob }: JobTabProps) {
    return (
        <ConversionJobs
            backend={backend}
            conversions={conversions}
            onOpenJob={onOpenJob}
        />
    )
}
