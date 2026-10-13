import { describe, expect, test } from "bun:test"
import type { ComponentProps } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { StatusBar } from "./status-bar"

const props: ComponentProps<typeof StatusBar> = {
    backend: { state: "starting", url: null, error: null, authRequired: null },
    isPolling: true,
    isAutoEnabled: true,
    isChecking: false,
    onRefresh: () => {},
    responseTimeMs: 12,
    lastCheckedAt: 1000,
    eventCount: 0,
    eventsOpen: false,
    onToggleEvents: () => {},
    toggleRef: null
}

function render(overrides: Partial<ComponentProps<typeof StatusBar>>) {
    return renderToStaticMarkup(
        <StatusBar
            {...props}
            {...overrides}
        />
    )
}

describe("sidecar polling status", () => {
    test("online inactivity is not described as a user pause or continuous polling", () => {
        const markup = render({
            backend: { state: "ready", url: "http://127.0.0.1:8001", error: null, authRequired: false },
            isPolling: false
        })
        expect(markup).toContain("Backend online")
        expect(markup).toContain("Online · idle")
        expect(markup).toContain("Automatic checks stop while the backend is online.")
        expect(markup).toContain("RPC 12 ms")
        expect(markup).not.toContain("paused")
        expect(markup).not.toContain("every 3 seconds")
    })

    test("active checks are described as offline-only and response-relative", () => {
        const markup = render({})
        expect(markup).toContain("Offline · auto-check")
        expect(markup).toContain(
            "Checking the offline sidecar every 3 seconds after each response until it is online or automatic checks are paused."
        )
        expect(markup).not.toContain("Auto-check paused")
        expect(markup).not.toContain("identical offline responses")
    })

    test("initial offline status waits for polling to start rather than claiming stable inactivity", () => {
        const markup = render({ isPolling: false, lastCheckedAt: null })
        expect(markup).toContain("Offline · waiting")
        expect(markup).toContain("No RPC response yet.")
        expect(markup).toContain("Waiting to start automatic offline checks.")
        expect(markup).not.toContain("Offline · idle")
        expect(markup).not.toContain("identical offline responses")
    })

    test("a paused preference still exposes the manual check control", () => {
        const markup = render({ isPolling: false, isAutoEnabled: false })
        expect(markup).toContain("Auto-check paused")
        expect(markup).toContain("paused by your preference")
        expect(markup).toContain("Manual checks are always available.")
        expect(markup).toContain('aria-label="Check sidecar now"')
        expect(markup).not.toContain('disabled=""')
        expect(markup).not.toContain("every 3 seconds")
    })

    test("a manual check has an honest loading label even when auto is paused", () => {
        const markup = render({ isPolling: false, isAutoEnabled: false, isChecking: true })
        expect(markup).toContain("Checking sidecar…")
        expect(markup).toContain('aria-busy="true"')
        expect(markup).toContain('disabled=""')
        expect(markup).not.toContain("Offline · auto-check")
    })
})
