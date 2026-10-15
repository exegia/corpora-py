import { useAtomValue, useSetAtom } from "jotai"
import { useEffect } from "react"
import type { SidecarStatus } from "@/shared/rpc"
import { backendEventsAtom, clearBackendEventsAtom, recordBackendEventAtom } from "@/shared/store"

export function useBackendEvents(backend: SidecarStatus) {
    const events = useAtomValue(backendEventsAtom)
    const recordEvent = useSetAtom(recordBackendEventAtom)
    const clearEvents = useSetAtom(clearBackendEventsAtom)

    useEffect(() => {
        recordEvent(backend)
    }, [backend, recordEvent])

    return { events, clearEvents }
}
