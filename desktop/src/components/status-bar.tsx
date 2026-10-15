import type { Ref } from "react"
import { Activity, ChevronUp, LockKeyhole, Radio, ShieldOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Status } from "@/components/ui/status"
import { RefreshSidecarButton } from "@/components/refresh-sidecar-button"
import type { SidecarStatus } from "@/shared/rpc"

interface StatusBarProps {
    backend: SidecarStatus
    isPolling: boolean
    isAutoEnabled?: boolean
    isChecking: boolean
    onRefresh: () => void
    responseTimeMs: number | null
    lastCheckedAt: number | null
    eventCount: number
    eventsOpen: boolean
    onToggleEvents: () => void
    toggleRef: Ref<HTMLButtonElement>
}

const labels = {
    starting: "Connecting",
    ready: "Backend online",
    failed: "Backend unavailable",
    stopped: "Backend stopped"
} as const

export function StatusBar({
    backend,
    isPolling,
    isAutoEnabled = true,
    isChecking,
    onRefresh,
    responseTimeMs,
    lastCheckedAt,
    eventCount,
    eventsOpen,
    onToggleEvents,
    toggleRef
}: StatusBarProps) {
    const AuthIcon = backend.authRequired ? LockKeyhole : ShieldOff
    const pollingLabel = isChecking
        ? "Checking sidecar…"
        : backend.state === "ready"
          ? "Online · idle"
          : !isAutoEnabled
            ? "Auto-check paused"
            : isPolling
              ? "Offline · auto-check"
              : "Offline · waiting"
    const pollingDetail =
        backend.state === "ready"
            ? "Automatic checks stop while the backend is online."
            : !isAutoEnabled
              ? "Automatic checks are paused by your preference."
              : isPolling
                ? "Checking the offline sidecar every 3 seconds after each response until it is online or automatic checks are paused."
                : "Waiting to start automatic offline checks."
    return (
        <footer
            aria-label="Workspace status"
            className=" h-10 inline-flex  row-span-1 items-center gap-3 px-4 text-xs text-muted-foreground">
            <div
                role="status"
                aria-live="polite"
                className="flex shrink-0 items-center gap-2">
                <Status
                    size="sm"
                    variant={
                        backend.state === "ready"
                            ? "success"
                            : backend.state === "starting"
                              ? "info"
                              : backend.state === "failed"
                                ? "destructive"
                                : "warning"
                    }
                />
                <span
                    className={
                        backend.state === "failed"
                            ? "font-medium text-destructive-foreground"
                            : "font-medium text-foreground"
                    }>
                    {labels[backend.state]}
                </span>
            </div>
            <span
                className="hidden h-3 w-px bg-border sm:block"
                aria-hidden="true"
            />
            <span
                className="hidden min-w-0 truncate font-mono sm:block"
                title={backend.url ?? backend.error ?? "Waiting for the sidecar endpoint"}>
                {backend.url ?? (backend.state === "starting" ? "Discovering loopback port…" : "No active endpoint")}
            </span>
            <div className="ml-auto flex shrink-0 items-center gap-3">
                <span
                    className="hidden items-center gap-1.5 lg:flex"
                    title={
                        backend.authRequired === null
                            ? "Authentication policy is not yet known"
                            : backend.authRequired
                              ? "Protected endpoints require a Supabase JWT"
                              : "Authentication is disabled for this local backend"
                    }>
                    <AuthIcon
                        className="size-3.5"
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                    {backend.authRequired === null
                        ? "Auth pending"
                        : backend.authRequired
                          ? "JWT protected"
                          : "Local / no auth"}
                </span>
                <span
                    className="hidden items-center gap-1.5 md:flex"
                    title={`${
                        lastCheckedAt === null
                            ? "No RPC response yet."
                            : `Last checked ${new Date(lastCheckedAt).toLocaleTimeString()}.`
                    } ${pollingDetail} Manual checks are always available.`}>
                    <Radio
                        className="size-3.5"
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                    <span className="font-mono tabular-nums">
                        {pollingLabel}
                        {responseTimeMs !== null && ` · RPC ${responseTimeMs} ms`}
                    </span>
                </span>
                <RefreshSidecarButton
                    compact
                    isChecking={isChecking}
                    onRefresh={onRefresh}
                />
                <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    ref={toggleRef}
                    aria-expanded={eventsOpen}
                    aria-controls={eventsOpen ? "workspace-events" : undefined}
                    onClick={onToggleEvents}>
                    <Activity aria-hidden="true" />
                    Events <span className="font-mono tabular-nums text-muted-foreground">{eventCount}</span>
                    <ChevronUp
                        aria-hidden="true"
                        className={eventsOpen ? "rotate-180" : ""}
                    />
                </Button>
            </div>
        </footer>
    )
}
