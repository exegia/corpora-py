import type { ConversionJob, ConversionJobsController } from "@/shared/conversion"
import type { SidecarStatus } from "@/shared/rpc"
import type { ResolvedTheme, Theme } from "@/shared/store-types"
import type { TabID } from "@/shared/navigation"

/** Runtime services supplied by App; editor components do not own their controllers. */
export interface WorkspaceViewProps {
    backend: SidecarStatus
    conversions: ConversionJobsController
    jobId?: string
    isActive: boolean
    isAutoEnabled: boolean
    isChecking: boolean
    responseTimeMs: number | null
    lastCheckedAt: number | null
    onRefresh: () => void
    onShowEvents: () => void
    onNavigate: (id: TabID) => void
    onOpenJob: (job: ConversionJob) => void
    pause: () => void
    resume: () => void
    theme: Theme
    resolvedTheme: ResolvedTheme
    setTheme: (theme: Theme) => void
}
