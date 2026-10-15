import { useAtomValue, useStore } from "jotai"
import { useEffect } from "react"
import { backendControllerAtom, backendSnapshotAtom } from "@/shared/store"

const useBackend = () => {
    const store = useStore()
    const polling = useAtomValue(backendControllerAtom)
    const snapshot = useAtomValue(backendSnapshotAtom)

    useEffect(() => {
        const publish = () => store.set(backendSnapshotAtom, polling.getSnapshot())
        const unsubscribe = polling.subscribe(publish)
        publish()
        polling.start()
        return () => {
            unsubscribe()
            polling.stop()
            publish()
        }
    }, [polling, store])

    return {
        ...snapshot,
        pause: polling.pause,
        resume: polling.resume,
        refresh: polling.refresh
    }
}

export default useBackend
