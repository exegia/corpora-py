import { useAtomValue, useStore } from "jotai"
import { useEffect } from "react"
import type { ConversionJobsController } from "@/shared/conversion"
import {
    backendAtom,
    conversionClientAtom,
    conversionSnapshotAtom,
    conversionSnapshotSourceAtom,
    lastEndpointAtom,
    resetConversionViewsAtom
} from "@/shared/store"

export function useConversionJobs(): ConversionJobsController {
    const store = useStore()
    const backend = useAtomValue(backendAtom)
    const client = useAtomValue(conversionClientAtom)
    const snapshot = useAtomValue(conversionSnapshotAtom)
    const online = backend.state === "ready" && Boolean(backend.url)

    useEffect(() => {
        if (!backend.url) return
        const previousEndpoint = store.get(lastEndpointAtom)
        if (previousEndpoint === backend.url) return
        store.set(lastEndpointAtom, backend.url)
        // Initial discovery and StrictMode remounts must not discard a user's draft.
        if (previousEndpoint !== null) store.set(resetConversionViewsAtom)
    }, [backend.url, store])

    useEffect(() => {
        const publish = () => {
            if (store.get(conversionClientAtom) === client) {
                store.set(conversionSnapshotSourceAtom, { client, snapshot: client.getSnapshot() })
            }
        }
        const unsubscribe = client.subscribe(publish)
        publish()
        if (online) client.start()
        return () => {
            unsubscribe()
            client.stop()
            publish()
        }
    }, [client, online, store])

    return {
        ...snapshot,
        refresh: client.refresh,
        submit: client.submit,
        download: client.download,
        clearError: client.clearError
    }
}
