import { ConversionJobDetail } from "@/components/conversion-job-detail"
import { Button } from "@/components/ui/button"
import type { WorkspaceViewProps } from "@/lib/workspace-view"

export function JobDetailTab({ jobId, conversions, backend, onNavigate }: WorkspaceViewProps) {
    const job = conversions.jobs.find((job) => job.id === jobId)
    return job ? (
        <ConversionJobDetail
            job={job}
            conversions={conversions}
            backendReady={backend.state === "ready"}
        />
    ) : (
        <div className="flex flex-col gap-3">
            <h1 className="text-lg font-semibold">Job unavailable</h1>
            <p className="text-sm text-muted-foreground">
                This job is no longer in the current sidecar session or request-token scope.
            </p>
            <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onNavigate("jobs")}>
                Open conversion jobs
            </Button>
        </div>
    )
}
