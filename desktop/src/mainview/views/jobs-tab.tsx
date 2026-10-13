import { ConversionJobs } from "@/components/conversion-jobs"
import { TabsContent } from "@/components/ui/tabs"
import { ConversionJobsController } from "@/shared/conversion"
import { SidecarStatus } from "@/shared/rpc"

interface IJobTabProps {
    backend: SidecarStatus
    conversions: ConversionJobsController
}

export const JobTab = ({ backend, conversions }: IJobTabProps) => {
    return (
        <TabsContent value="jobs">
            <ConversionJobs
                backend={backend}
                conversions={conversions}
            />
        </TabsContent>
    )
}
