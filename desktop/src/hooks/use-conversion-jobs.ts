import { useEffect, useMemo, useState, useSyncExternalStore } from "react"
import { ConversionClient } from "@/lib/conversion-client"
import type { ConversionJobsController } from "@/shared/conversion"
import type { SidecarStatus } from "@/shared/rpc"

export function useConversionJobs(backend: SidecarStatus, token: string): ConversionJobsController {
    const [lastEndpoint, setLastEndpoint] = useState<string | null>(backend.url)
    useEffect(() => {
        if (backend.url) setLastEndpoint(backend.url)
    }, [backend.url])
    // Preserve observed jobs during an outage, but isolate a new endpoint or identity.
    const endpoint = backend.url ?? lastEndpoint
    const client = useMemo(() => new ConversionClient(endpoint, token), [endpoint, token])
    const snapshot = useSyncExternalStore(client.subscribe, client.getSnapshot, client.getSnapshot)
    const online = backend.state === "ready" && Boolean(backend.url)
    useEffect(() => {
        if (online) client.start()
        return client.stop
    }, [client, online])
    return { ...snapshot, refresh: client.refresh, submit: client.submit, download: client.download, clearError: client.clearError }
}
