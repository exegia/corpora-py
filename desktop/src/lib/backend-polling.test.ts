import { describe, expect, mock, test } from "bun:test"
import { BackendPolling, type BackendPollingClock } from "./backend-polling"
import type { SidecarStatus } from "../shared/rpc"

const starting: SidecarStatus = { state: "starting", url: null, error: null, authRequired: null }
const ready: SidecarStatus = { state: "ready", url: "http://127.0.0.1:8001", error: null, authRequired: false }
const failed: SidecarStatus = { ...starting, state: "failed", error: "Python is unavailable" }

class TestClock implements BackendPollingClock {
    time = 1000
    private sequence = 0
    timers = new Map<number, { callback: () => Promise<void>; delayMs: number }>()
    now = () => this.time
    monotonicNow = () => this.time
    schedule = (callback: () => Promise<void>, delayMs: number) => {
        const id = ++this.sequence
        this.timers.set(id, { callback, delayMs })
        return () => {
            this.timers.delete(id)
        }
    }
    async tick(): Promise<void> {
        const entry = this.timers.entries().next().value
        if (!entry) throw new Error("No automatic check is scheduled")
        const [id, timer] = entry
        this.timers.delete(id)
        expect(timer.delayMs).toBe(3000)
        this.time += timer.delayMs
        await timer.callback()
    }
}

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((done, fail) => {
        resolve = done
        reject = fail
    })
    return { promise, resolve, reject }
}

function harness(read: () => Promise<SidecarStatus>) {
    const clock = new TestClock()
    const readStatus = mock(read)
    const polling = new BackendPolling(readStatus, clock)
    polling.start()
    return { clock, readStatus, polling }
}

describe("offline-only sidecar polling", () => {
    test("stops immediately on ready without disabling the user's preference", async () => {
        const { polling, readStatus, clock } = harness(async () => ready)
        await polling.refresh()
        expect(readStatus).toHaveBeenCalledTimes(1)
        expect(polling.getSnapshot()).toMatchObject({
            backend: ready,
            isAutoEnabled: true,
            isActive: false,
            isChecking: false
        })
        expect(clock.timers.size).toBe(0)
        polling.resume()
        expect(clock.timers.size).toBe(0)
        expect(readStatus).toHaveBeenCalledTimes(1)
        polling.stop()
    })

    test.each([starting, failed, { ...starting, state: "stopped" } satisfies SidecarStatus])(
        "keeps polling identical %j responses until automatic recovery without replacing backend state",
        async (offline) => {
            let status = offline
            const { polling, readStatus, clock } = harness(async () => ({ ...status }))
            await polling.refresh()
            const firstBackend = polling.getSnapshot().backend
            for (let i = 0; i < 6; i++) {
                await clock.tick()
                expect(polling.getSnapshot()).toMatchObject({ isActive: true, isAutoEnabled: true, isChecking: false })
                expect(polling.getSnapshot().backend).toBe(firstBackend)
                expect(clock.timers.size).toBe(1)
            }
            expect(readStatus).toHaveBeenCalledTimes(7)
            expect(polling.getSnapshot().lastCheckedAt).toBe(19000)
            status = ready
            await clock.tick()
            expect(readStatus).toHaveBeenCalledTimes(8)
            expect(polling.getSnapshot()).toMatchObject({ backend: ready, isActive: false, isAutoEnabled: true })
            expect(clock.timers.size).toBe(0)
            polling.stop()
        }
    )

    test("a manual online-to-offline observation resumes automatic checks until recovery", async () => {
        let status = ready
        const { polling, readStatus, clock } = harness(async () => status)
        await polling.refresh()
        expect(polling.getSnapshot().isActive).toBe(false)
        status = failed
        await polling.refresh()
        expect(readStatus).toHaveBeenCalledTimes(2)
        expect(polling.getSnapshot()).toMatchObject({ backend: failed, isActive: true, isAutoEnabled: true })
        expect(clock.timers.size).toBe(1)
        status = ready
        await clock.tick()
        expect(readStatus).toHaveBeenCalledTimes(3)
        expect(polling.getSnapshot().isActive).toBe(false)
        expect(clock.timers.size).toBe(0)
        polling.stop()
    })

    test.each([
        { state: "starting" },
        { url: "http://127.0.0.1:9000" },
        { error: "Python is restarting" },
        { authRequired: true }
    ] satisfies Partial<SidecarStatus>[])(
        "a changed %j field publishes a new backend snapshot while offline polling continues",
        async (change) => {
            let status = failed
            const { polling, clock } = harness(async () => ({ ...status }))
            await polling.refresh()
            const previousBackend = polling.getSnapshot().backend
            await clock.tick()
            expect(polling.getSnapshot().backend).toBe(previousBackend)
            status = { ...failed, ...change }
            await clock.tick()
            const changedBackend = polling.getSnapshot().backend
            expect(changedBackend).toEqual(status)
            expect(changedBackend).not.toBe(previousBackend)
            await clock.tick()
            expect(polling.getSnapshot().backend).toBe(changedBackend)
            expect(polling.getSnapshot().isActive).toBe(true)
            expect(clock.timers.size).toBe(1)
            polling.stop()
        }
    )

    test("pause clears the timer; manual refresh works while paused without re-enabling auto", async () => {
        let status = starting
        const { polling, readStatus, clock } = harness(async () => status)
        await polling.refresh()
        polling.pause()
        expect(polling.getSnapshot()).toMatchObject({ isAutoEnabled: false, isActive: false })
        expect(clock.timers.size).toBe(0)
        status = failed
        await polling.refresh()
        expect(readStatus).toHaveBeenCalledTimes(2)
        expect(polling.getSnapshot()).toMatchObject({
            backend: failed,
            isAutoEnabled: false,
            isActive: false,
            isChecking: false
        })
        expect(clock.timers.size).toBe(0)
        polling.resume()
        await polling.refresh()
        expect(readStatus).toHaveBeenCalledTimes(3)
        expect(polling.getSnapshot()).toMatchObject({ isAutoEnabled: true, isActive: true })
        expect(clock.timers.size).toBe(1)
        polling.stop()
    })

    test("background checks do not publish a loading state or flicker the manual control", async () => {
        const response = deferred<SidecarStatus>()
        let initial = true
        const { polling, clock, readStatus } = harness(() => {
            if (initial) {
                initial = false
                return Promise.resolve(starting)
            }
            return response.promise
        })
        await polling.refresh()
        const beforeCheck = polling.getSnapshot()
        const listener = mock(() => {})
        const unsubscribe = polling.subscribe(listener)
        const background = clock.tick()
        expect(polling.getSnapshot()).toBe(beforeCheck)
        expect(polling.getSnapshot().isChecking).toBe(false)
        expect(listener).not.toHaveBeenCalled()
        await Promise.resolve()
        expect(readStatus).toHaveBeenCalledTimes(2)
        response.resolve({ ...starting })
        await background
        expect(polling.getSnapshot().isChecking).toBe(false)
        expect(polling.getSnapshot().backend).toBe(beforeCheck.backend)
        expect(listener).toHaveBeenCalledTimes(1)
        expect(clock.timers.size).toBe(1)
        unsubscribe()
        polling.stop()
    })

    test("a manual refresh joins an in-flight background RPC and shows its loading state", async () => {
        const response = deferred<SidecarStatus>()
        let initial = true
        const { polling, clock, readStatus } = harness(() => {
            if (initial) {
                initial = false
                return Promise.resolve(starting)
            }
            return response.promise
        })
        await polling.refresh()
        const background = clock.tick()
        expect(polling.getSnapshot().isChecking).toBe(false)
        const manual = polling.refresh()
        expect(polling.refresh()).toBe(manual)
        expect(polling.getSnapshot().isChecking).toBe(true)
        await Promise.resolve()
        expect(readStatus).toHaveBeenCalledTimes(2)
        response.resolve(failed)
        await manual
        await background
        expect(polling.getSnapshot()).toMatchObject({ backend: failed, isActive: true, isChecking: false })
        expect(clock.timers.size).toBe(1)
        polling.stop()
    })

    test("manual and automatic requests are singleflight and use response-relative timing", async () => {
        const response = deferred<SidecarStatus>()
        const { polling, readStatus, clock } = harness(() => response.promise)
        const automatic = polling.refresh()
        const manual = polling.refresh()
        expect(manual).toBe(automatic)
        expect(polling.getSnapshot().isChecking).toBe(true)
        expect(clock.timers.size).toBe(0)
        await Promise.resolve()
        expect(readStatus).toHaveBeenCalledTimes(1)
        clock.time += 125
        response.resolve(starting)
        await manual
        expect(polling.getSnapshot()).toMatchObject({ isChecking: false, lastCheckedAt: 1125, responseTimeMs: 125 })
        expect(clock.timers.size).toBe(1)
        // A manual check replaces the scheduled timer, rather than leaving two loops.
        await polling.refresh()
        expect(readStatus).toHaveBeenCalledTimes(2)
        expect(clock.timers.size).toBe(1)
        polling.stop()
    })

    test("pause during an in-flight check suppresses scheduling but preserves its result", async () => {
        const response = deferred<SidecarStatus>()
        const { polling, clock } = harness(() => response.promise)
        const request = polling.refresh()
        polling.pause()
        response.resolve(starting)
        await request
        expect(polling.getSnapshot()).toMatchObject({
            isAutoEnabled: false,
            isActive: false,
            isChecking: false,
            lastCheckedAt: 1000
        })
        expect(clock.timers.size).toBe(0)
        polling.stop()
    })

    test("StrictMode stop/start shares an in-flight RPC and creates only one timer", async () => {
        const response = deferred<SidecarStatus>()
        const { polling, readStatus, clock } = harness(() => response.promise)
        const request = polling.refresh()
        polling.stop()
        polling.start()
        expect(polling.refresh()).toBe(request)
        response.resolve(starting)
        await request
        expect(readStatus).toHaveBeenCalledTimes(1)
        expect(polling.getSnapshot()).toMatchObject({ isChecking: false, isActive: true })
        expect(clock.timers.size).toBe(1)
        polling.stop()
    })

    test("unmount clears a scheduled check and prevents later manual requests", async () => {
        const { polling, clock, readStatus } = harness(async () => starting)
        await polling.refresh()
        expect(clock.timers.size).toBe(1)
        polling.stop()
        expect(clock.timers.size).toBe(0)
        await polling.refresh()
        expect(readStatus).toHaveBeenCalledTimes(1)
        expect(polling.getSnapshot().isActive).toBe(false)
    })

    test.each([false, true])(
        "unmount ignores late RPC completion (rejected: %j) and never notifies",
        async (rejected) => {
            const response = deferred<SidecarStatus>()
            const { polling, clock } = harness(() => response.promise)
            const listener = mock(() => {})
            const unsubscribe = polling.subscribe(listener)
            const request = polling.refresh()
            polling.stop()
            const stoppedSnapshot = polling.getSnapshot()
            if (rejected) response.reject(new Error("RPC timed out"))
            else response.resolve(ready)
            await request
            expect(polling.getSnapshot()).toBe(stoppedSnapshot)
            expect(polling.getSnapshot()).toMatchObject({ isActive: false, isChecking: false, lastCheckedAt: null })
            expect(listener).not.toHaveBeenCalled()
            expect(clock.timers.size).toBe(0)
            unsubscribe()
        }
    )

    test("repeated RPC failures keep polling and recover automatically; a synchronous throw cannot wedge singleflight", async () => {
        let broken = true
        const { polling, clock, readStatus } = harness(() => {
            if (broken) throw new Error("RPC timed out")
            return Promise.resolve(ready)
        })
        await polling.refresh()
        expect(polling.getSnapshot()).toMatchObject({
            backend: { ...failed, error: "RPC timed out" },
            isChecking: false,
            isActive: true,
            lastCheckedAt: 1000,
            responseTimeMs: null
        })
        for (let i = 0; i < 5; i++) {
            await clock.tick()
            expect(polling.getSnapshot()).toMatchObject({ isChecking: false, isActive: true, responseTimeMs: null })
            expect(clock.timers.size).toBe(1)
        }
        broken = false
        await clock.tick()
        expect(readStatus).toHaveBeenCalledTimes(7)
        expect(polling.getSnapshot()).toMatchObject({ backend: ready, isActive: false, isChecking: false })
        expect(clock.timers.size).toBe(0)
        polling.stop()
    })
})
