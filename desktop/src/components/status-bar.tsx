import type { ComponentProps, Ref } from "react"
import { ChevronUp, type LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Status } from "@/components/ui/status"
import { RefreshSidecarButton } from "@/components/refresh-sidecar-button"
import type { SidecarStatus } from "@/shared/rpc"
import { cn } from "@/lib/utils"

import {
    Activity,
    LockKeyhole,
    MessageSquareWarning,
    ScanLine,
    Power,
    Radio,
    Server,
    ServerOff,
    ShieldOff,
    IconNode,
    ServerCrash
} from "lucide"
import { MorphIcon } from "morphicons/react"

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

const pollingStates = {
    running: {
        state: "running",
        label: "Offline · auto-check",
        detail: "Checking the offline sidecar every 3 seconds after each response until it is online or automatic checks are paused."
    },
    idle: {
        state: "idle",
        label: "Online · idle",
        detail: "Automatic checks stop while the backend is online."
    },
    paused: {
        state: "paused",
        label: "Auto-check paused",
        detail: "Automatic checks are paused by your preference."
    },
    waiting: {
        state: "waiting",
        label: "Offline · waiting",
        detail: "Waiting to start automatic offline checks."
    },
    checking: {
        state: "checking",
        label: "Checking sidecar…"
    }
} as const

interface BackendState {
    message: string
    description: string
    endpoint: string
    icon: IconNode
    indicator?: Pick<ComponentProps<typeof Status>, "variant" | "className">
    textClassName: string
    backgroundClassName: string
    polling: typeof pollingStates.running | typeof pollingStates.idle
}

const animatedClassDefault =
    "animate-duration-1000 animate-delay-300 animate-steps-modern animate-iteration-count-infinite animate-fill-mode-both"

const backendStates = {
    starting: {
        message: "Connecting...",
        description: "Waiting for the sidecar endpoint",
        endpoint: "Discovering loopback port…",
        icon: ScanLine,
        indicator: { variant: "info", className: "animate-flash" },
        backgroundClassName: "hover:bg-info/5",
        textClassName: "text-foreground hover:text-info-foreground",
        polling: pollingStates.running
    },
    ready: {
        message: "online",
        description: "The backend is online.",
        endpoint: "No active endpoint",
        icon: Server,
        backgroundClassName: "",
        indicator: { variant: "success", className: "animate-pulsing" },
        textClassName: "text-success hover:text-success-foreground",
        polling: pollingStates.idle
    },
    failed: {
        message: "failed",
        description: "The backend is unavailable.",
        endpoint: "No active endpoint",
        icon: ServerCrash,
        backgroundClassName: "text-warning hover:text-warning-foreground",
        indicator: { variant: "destructive" },
        textClassName: "",
        polling: pollingStates.running
    },
    stopped: {
        message: "stopped",
        description: "The backend is stopped.",
        backgroundClassName: "bg-secondary/70",
        endpoint: "No active endpoint",
        icon: ServerOff,
        indicator: {},
        textClassName: "text-foreground",
        polling: pollingStates.running
    }
} as const satisfies Record<SidecarStatus["state"], BackendState>

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
    const backendState = backendStates[backend.state]
    const BackendIcon = backendState.icon
    const AuthIcon = backend.authRequired ? LockKeyhole : ShieldOff
    const automaticPolling =
        backendState.polling.state === "idle"
            ? backendState.polling
            : !isAutoEnabled
              ? pollingStates.paused
              : isPolling
                ? backendState.polling
                : pollingStates.waiting
    const polling = isChecking ? { ...automaticPolling, ...pollingStates.checking } : automaticPolling
    return (
        <footer
            aria-label="Workspace status"
            className=" h-10 inline-flex  row-span-1 items-center gap-3 px-4 text-xs text-muted-foreground">
            <Button
                type="button"
                variant="ghost"
                size="xs"
                ref={toggleRef}
                className={cn("rounded-sm", backendState.backgroundClassName)}
                aria-expanded={eventsOpen}
                aria-controls={eventsOpen ? "workspace-events" : undefined}
                onClick={onToggleEvents}>
                <MorphIcon
                    className={cn(
                        animatedClassDefault,
                        "size-2.5",
                        backendState.textClassName,
                        "className" in backendState.indicator && backendState.indicator.className
                    )}
                    icon={backendState.icon}
                    aria-hidden="true"
                />
                <span className={cn("font-medium")}>{backendState.message}</span>
            </Button>

            <span
                className="hidden h-3 w-px bg-border sm:block"
                aria-hidden="true"
            />
            <span
                className="hidden min-w-0 truncate font-mono sm:block"
                title={backend.url ?? backend.error ?? backendState.description}>
                {backend.url ?? backendState.endpoint}
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
                    <MorphIcon
                        icon={AuthIcon}
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
                    data-state={polling.state}
                    title={`${
                        lastCheckedAt === null
                            ? "No RPC response yet."
                            : `Last checked ${new Date(lastCheckedAt).toLocaleTimeString()}.`
                    } ${polling.detail} Manual checks are always available.`}>
                    <MorphIcon
                        icon={Radio}
                        className="size-3.5"
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                    <span className="font-mono tabular-nums">
                        {polling.label}
                        {responseTimeMs !== null && ` · RPC ${responseTimeMs} ms`}
                    </span>
                </span>
                {/*<RefreshSidecarButton
                    compact
                    isChecking={isChecking}
                    onRefresh={onRefresh}
                />
               */}
            </div>
        </footer>
    )
}
