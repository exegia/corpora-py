import { describe, expect, test } from "bun:test"
import { describeBackendEvent } from "./backend-events"
import type { SidecarStatus } from "../shared/rpc"

const starting: SidecarStatus = { state: "starting", url: null, error: null, authRequired: null }
const ready: SidecarStatus = { state: "ready", url: "http://127.0.0.1:8001", error: null, authRequired: false }

describe("observed backend events", () => {
    test("records startup and readiness with the actual endpoint", () => {
        expect(describeBackendEvent(null, starting)?.level).toBe("info")
        expect(describeBackendEvent(starting, ready)?.message).toContain(ready.url!)
    })
    test("does not duplicate unchanged poll responses", () => {
        expect(describeBackendEvent(ready, { ...ready })).toBeNull()
    })
    test("reports failures, shutdown and recovery", () => {
        const failed: SidecarStatus = { ...starting, state: "failed", error: "RPC timed out" }
        expect(describeBackendEvent(ready, failed)).toEqual({ level: "error", message: "RPC timed out" })
        expect(describeBackendEvent(failed, ready)?.level).toBe("success")
        expect(describeBackendEvent(ready, { ...starting, state: "stopped" })?.level).toBe("warning")
    })
    test("records changed endpoints and auth without claiming unknown auth is disabled", () => {
        expect(describeBackendEvent(ready, { ...ready, authRequired: true })?.message).toContain("JWT")
        expect(describeBackendEvent(ready, { ...ready, authRequired: null })?.message).toContain("unknown")
        expect(describeBackendEvent(ready, { ...ready, url: "http://127.0.0.1:9000" })?.message).toContain(":9000")
    })
})
