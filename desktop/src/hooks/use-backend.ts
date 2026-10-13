import { BackendPolling } from "@/lib/backend-polling"
import { getSidecarStatus } from "@/mainview/backend"
import { useEffect, useRef, useSyncExternalStore } from "react"

const useBackend = () => {
    const controller = useRef<BackendPolling | null>(null)
    if (controller.current === null) controller.current = new BackendPolling(getSidecarStatus)
    const polling = controller.current
    const snapshot = useSyncExternalStore(polling.subscribe, polling.getSnapshot, polling.getSnapshot)

    useEffect(() => {
        polling.start()
        return polling.stop
    }, [polling])

    return {
        ...snapshot,
        pause: polling.pause,
        resume: polling.resume,
        refresh: polling.refresh
    }
}

export default useBackend
