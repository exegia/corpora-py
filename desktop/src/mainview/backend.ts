import { Electroview } from "electrobun/view"
import type { DesktopRPC, SidecarStatus } from "../shared/rpc"

function createBridge() {
    const rpc = Electroview.defineRPC<DesktopRPC>({
        maxRequestTime: 5000,
        handlers: { requests: {}, messages: {} }
    })
    if (window.__electrobun) new Electroview({ rpc })
    return rpc
}

// Keep the transport across accepted HMR updates as well as React StrictMode mounts.
const hotData: { bridge?: ReturnType<typeof createBridge> } | undefined = import.meta.hot?.data
const rpc = hotData?.bridge ?? createBridge()
if (import.meta.hot) {
    import.meta.hot.data.bridge = rpc
    import.meta.hot.accept()
}

export async function getSidecarStatus(): Promise<SidecarStatus> {
    if (!window.__electrobun) {
        throw new Error("Open the Electrobun app, not the Vite URL in a standalone browser, to use its Python sidecar.")
    }
    return rpc.request.getSidecarStatus({})
}

export async function getBackendUrl(): Promise<string> {
    const status = await getSidecarStatus()
    if (status.state !== "ready" || !status.url) {
        throw new Error(status.error ?? `Python backend is ${status.state}.`)
    }
    return status.url
}

/** Attach a Supabase Bearer header via init.headers when authRequired is true. */
export async function backendFetch(path: string, init?: RequestInit): Promise<Response> {
    if (!path.startsWith("/") || path.startsWith("//")) {
        throw new Error("Backend paths must start with a single slash.")
    }
    return fetch(`${await getBackendUrl()}${path}`, init)
}
