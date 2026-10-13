import { getSidecarStatus } from "@/mainview/backend"
import type { SidecarStatus } from "@/shared/rpc"
import { useState, useCallback, useEffect, useRef } from "react"

const POLL_INTERVAL_MS = 3000

const useBackend = () => {
    const [backend, setBackend] = useState<SidecarStatus>({
        state: "starting",
        url: null,
        error: null,
        authRequired: null
    })
    const [isActive, setIsActive] = useState(true)
    const [isChecking, setIsChecking] = useState(false)
    const [diagnostics, setDiagnostics] = useState<{
        lastCheckedAt: number | null
        responseTimeMs: number | null
    }>({ lastCheckedAt: null, responseTimeMs: null })
    const mounted = useRef(false)
    const pendingRequest = useRef<Promise<void> | null>(null)
    const pause = useCallback(() => setIsActive(false), [])
    const resume = useCallback(() => setIsActive(true), [])

    useEffect(() => {
        mounted.current = true
        return () => {
            mounted.current = false
        }
    }, [])

    const refresh = useCallback((): Promise<void> => {
        if (!mounted.current) return Promise.resolve()
        // Manual checks and polling share one RPC, including across StrictMode effects.
        if (pendingRequest.current) return pendingRequest.current

        setIsChecking(true)
        const startedAt = performance.now()
        const request = (async () => {
            let responseTimeMs: number | null = null
            try {
                const status = await getSidecarStatus()
                responseTimeMs = Math.round(performance.now() - startedAt)
                if (mounted.current) setBackend(status)
            } catch (error) {
                if (mounted.current) {
                    setBackend({
                        state: "failed",
                        url: null,
                        authRequired: null,
                        error: error instanceof Error ? error.message : String(error)
                    })
                }
            } finally {
                pendingRequest.current = null
                if (mounted.current) {
                    setDiagnostics({ lastCheckedAt: Date.now(), responseTimeMs })
                    setIsChecking(false)
                }
            }
        })()
        pendingRequest.current = request
        return request
    }, [])

    useEffect(() => {
        if (!isActive) return

        let cancelled = false
        let timer: ReturnType<typeof setTimeout> | undefined
        const poll = async () => {
            await refresh()
            // Pausing stops future polls, not a shared check already in progress.
            if (!cancelled) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS)
        }

        void poll()
        return () => {
            cancelled = true
            if (timer !== undefined) clearTimeout(timer)
        }
    }, [isActive, refresh])

    return {
        isActive,
        isChecking,
        pause,
        resume,
        refresh,
        backend,
        ...diagnostics
    }
}

export default useBackend
