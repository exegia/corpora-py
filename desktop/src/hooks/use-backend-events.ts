import { useCallback, useEffect, useRef, useState } from "react"
import { describeBackendEvent, type BackendEvent } from "@/lib/backend-events"
import type { SidecarStatus } from "@/shared/rpc"

export function useBackendEvents(backend: SidecarStatus) {
    const [events, setEvents] = useState<BackendEvent[]>([])
    const previous = useRef<SidecarStatus | null>(null)
    const sequence = useRef(0)

    useEffect(() => {
        const description = describeBackendEvent(previous.current, backend)
        previous.current = backend
        if (!description) return
        const event: BackendEvent = { ...description, id: ++sequence.current, timestamp: Date.now() }
        setEvents(current => [event, ...current].slice(0, 50))
    }, [backend])

    const clearEvents = useCallback(() => setEvents([]), [])
    return { events, clearEvents }
}
