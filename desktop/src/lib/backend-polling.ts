import type { SidecarStatus } from "@/shared/rpc"

const POLL_INTERVAL_MS = 3000

export interface BackendPollingSnapshot {
    backend: SidecarStatus
    isAutoEnabled: boolean
    isActive: boolean
    isChecking: boolean
    lastCheckedAt: number | null
    responseTimeMs: number | null
}

export interface BackendPollingClock {
    now: () => number
    monotonicNow: () => number
    schedule: (callback: () => Promise<void>, delayMs: number) => () => void
}

const defaultClock: BackendPollingClock = {
    now: () => Date.now(),
    monotonicNow: () => performance.now(),
    schedule: (callback, delayMs) => {
        const timer = setTimeout(callback, delayMs)
        return () => clearTimeout(timer)
    }
}

function sameStatus(previous: SidecarStatus, current: SidecarStatus): boolean {
    return (
        previous.state === current.state &&
        previous.url === current.url &&
        previous.error === current.error &&
        previous.authRequired === current.authRequired
    )
}

/** One response-driven polling loop shared by automatic and manual checks. */
export class BackendPolling {
    private snapshot: BackendPollingSnapshot = {
        backend: { state: "starting", url: null, error: null, authRequired: null },
        isAutoEnabled: true,
        isActive: false,
        isChecking: false,
        lastCheckedAt: null,
        responseTimeMs: null
    }
    private mounted = false

    private pendingRequest: Promise<void> | null = null
    private cancelTimer: (() => void) | null = null
    private listeners = new Set<() => void>()

    constructor(
        private readonly readStatus: () => Promise<SidecarStatus>,
        private readonly clock: BackendPollingClock = defaultClock
    ) {}

    getSnapshot = (): BackendPollingSnapshot => this.snapshot

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => this.listeners.delete(listener)
    }

    private publish(update: Partial<BackendPollingSnapshot>): void {
        const next = { ...this.snapshot, ...update }
        next.isActive = this.mounted && next.isAutoEnabled && next.backend.state !== "ready"
        this.snapshot = next
        if (this.mounted) for (const listener of this.listeners) listener()
    }

    private clearTimer(): void {
        this.cancelTimer?.()
        this.cancelTimer = null
    }

    start = (): void => {
        if (this.mounted) return
        this.mounted = true
        this.publish({ isChecking: this.pendingRequest !== null })
        if (this.snapshot.isActive) void this.refresh()
    }

    stop = (): void => {
        this.mounted = false
        this.clearTimer()
        // The RPC cannot be cancelled. Ignore late results, but retain singleflight
        // when React StrictMode immediately starts this same instance again.
        this.publish({ isChecking: false })
    }

    pause = (): void => {
        this.clearTimer()
        this.publish({ isAutoEnabled: false })
    }

    resume = (): void => {
        this.publish({ isAutoEnabled: true })
        if (this.snapshot.isActive) void this.refresh()
    }

    refresh = (): Promise<void> => this.check(true)

    private check(showChecking: boolean): Promise<void> {
        if (!this.mounted) return Promise.resolve()
        if (this.pendingRequest) {
            // A manual check can join a silent background RPC and show its progress.
            if (showChecking && !this.snapshot.isChecking) this.publish({ isChecking: true })
            return this.pendingRequest
        }

        this.clearTimer()
        if (showChecking) this.publish({ isChecking: true })
        const startedAt = this.clock.monotonicNow()
        // Defer invocation so even a synchronous transport failure shares and
        // clears the assigned pending promise correctly.
        const request = Promise.resolve()
            .then(this.readStatus)
            .then(
                (status) => ({ status, responseTimeMs: Math.round(this.clock.monotonicNow() - startedAt) }),
                (error: unknown) => ({
                    status: {
                        state: "failed",
                        url: null,
                        authRequired: null,
                        error: error instanceof Error ? error.message : String(error)
                    } satisfies SidecarStatus,
                    responseTimeMs: null
                })
            )
            .then(({ status, responseTimeMs }) => {
                this.pendingRequest = null
                if (!this.mounted) return

                const identical = sameStatus(this.snapshot.backend, status)

                this.publish({
                    backend: identical ? this.snapshot.backend : status,
                    isChecking: false,
                    lastCheckedAt: this.clock.now(),
                    responseTimeMs
                })
                // Identical offline responses still need checks for eventual recovery.
                // Only readiness or the user's preference stops the mounted loop.
                if (this.snapshot.isActive) {
                    this.cancelTimer = this.clock.schedule(() => {
                        this.cancelTimer = null
                        return this.check(false)
                    }, POLL_INTERVAL_MS)
                }
            })
        this.pendingRequest = request
        return request
    }
}
