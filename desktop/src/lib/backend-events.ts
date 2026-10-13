import type { SidecarStatus } from "@/shared/rpc"

export interface BackendEvent {
    id: number
    timestamp: number
    level: "info" | "success" | "warning" | "error"
    message: string
}

export function describeBackendEvent(previous: SidecarStatus | null, current: SidecarStatus): Pick<BackendEvent, "level" | "message"> | null {
    if (previous?.state === current.state && previous.url === current.url && previous.error === current.error && previous.authRequired === current.authRequired) return null
    switch (current.state) {
        case "starting":
            return { level: "info", message: "Waiting for the managed Python backend." }
        case "failed":
            return { level: "error", message: current.error ?? "The Python backend is unavailable." }
        case "stopped":
            return { level: "warning", message: "The Python backend has stopped." }
        case "ready":
            return {
                level: "success",
                message: `Backend ready${current.url ? ` at ${current.url}` : ""}. ${current.authRequired === null ? "Auth policy unknown." : current.authRequired ? "JWT authentication required." : "Local authentication disabled."}`
            }
    }
}
