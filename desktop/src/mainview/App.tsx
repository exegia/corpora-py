import { useRef, useState, type ReactNode } from "react"
import {
    Activity,
    ArrowUpRight,
    Compass,
    Database,
    FolderClock,
    LayoutDashboard,
    LockKeyhole,
    Monitor,
    Radio,
    Settings2,
    Terminal
} from "lucide-react"
import useBackend from "@/hooks/use-backend"
import { useBackendEvents } from "@/hooks/use-backend-events"
import { useTheme } from "@/hooks/use-theme"
import { TitleBar } from "@/components/title-bar"
import { ThemeToggle } from "@/components/theme-toggle"
import { StatusBar } from "@/components/status-bar"
import { RefreshSidecarButton } from "@/components/refresh-sidecar-button"
import { ActivityPanel } from "@/components/activity-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

const navigation = [
    { value: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { value: "jobs", label: "Jobs", icon: FolderClock },
    { value: "explorer", label: "Explorer", icon: Compass },
    { value: "settings", label: "Settings", icon: Settings2 }
]

function PanelHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
    return (
        <div className="mb-7 flex flex-col gap-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">{eyebrow}</p>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">{children}</p>
        </div>
    )
}

function App() {
    const { backend, isActive, isChecking, pause, resume, refresh, lastCheckedAt, responseTimeMs } = useBackend()
    const { events, clearEvents } = useBackendEvents(backend)
    const { theme, resolvedTheme } = useTheme()
    const [activeTab, setActiveTab] = useState("dashboard")
    const [eventsOpen, setEventsOpen] = useState(false)
    const tabTriggers = useRef<Record<string, HTMLButtonElement | null>>({})
    const eventsToggle = useRef<HTMLButtonElement | null>(null)
    const navigateTo = (value: string) => {
        setActiveTab(value)
        tabTriggers.current[value]?.focus()
    }
    const closeEvents = () => {
        setEventsOpen(false)
        eventsToggle.current?.focus()
    }
    const authLabel =
        backend.authRequired === null ? "Awaiting policy" : backend.authRequired ? "JWT protected" : "Local development"

    return (
        <div className="desktop-shell flex h-dvh min-h-0 w-full flex-col overflow-hidden bg-background text-foreground">
            <TitleBar />
            <Tabs
                value={activeTab}
                onValueChange={({ value }) => setActiveTab(value)}
                className="min-h-0 flex-1 gap-0">
                <nav
                    aria-label="Workspace navigation"
                    className="shrink-0 border-b border-border bg-card px-4 sm:px-7">
                    <TabsList
                        variant="underline"
                        aria-label="Workspace sections"
                        className="max-w-full">
                        {navigation.map(({ value, label, icon: Icon }) => (
                            <TabsTrigger
                                key={value}
                                value={value}
                                ref={(node) => {
                                    tabTriggers.current[value] = node
                                }}
                                className="h-11 px-3 sm:px-4">
                                <Icon
                                    aria-hidden="true"
                                    strokeWidth={1.5}
                                />
                                {label}
                            </TabsTrigger>
                        ))}
                    </TabsList>
                </nav>
                <main className="min-h-0 flex-1 overflow-y-auto">
                    <div className="mx-auto w-full max-w-5xl px-5 py-8 sm:px-8">
                        <TabsContent value="dashboard">
                            <PanelHeading
                                eyebrow="Workspace overview"
                                title="Your corpus workspace.">
                                Convert, inspect, and work with your texts. A managed Python runtime keeps the backend
                                close to your desktop.
                            </PanelHeading>
                            <div className="grid gap-4 sm:grid-cols-3">
                                <section className="rounded-xl border border-border bg-card p-5">
                                    <div className="mb-5 flex items-center justify-between">
                                        <span className="text-xs font-medium text-muted-foreground">
                                            Python runtime
                                        </span>
                                        <Database
                                            className="size-4 text-muted-foreground"
                                            aria-hidden="true"
                                            strokeWidth={1.5}
                                        />
                                    </div>
                                    <p className="text-lg font-semibold capitalize tracking-tight">{backend.state}</p>
                                    <p className="mt-1 text-xs text-muted-foreground">Desktop-owned sidecar</p>
                                </section>
                                <section className="rounded-xl border border-border bg-card p-5">
                                    <div className="mb-5 flex items-center justify-between">
                                        <span className="text-xs font-medium text-muted-foreground">RPC response</span>
                                        <Radio
                                            className="size-4 text-muted-foreground"
                                            aria-hidden="true"
                                            strokeWidth={1.5}
                                        />
                                    </div>
                                    <p className="text-lg font-semibold tabular-nums tracking-tight">
                                        {responseTimeMs === null ? "—" : `${responseTimeMs} ms`}
                                    </p>
                                    <p className="mt-1 text-xs text-muted-foreground">
                                        {isActive ? "Monitoring every 3 seconds" : "Monitoring paused"}
                                    </p>
                                </section>
                                <section className="rounded-xl border border-border bg-card p-5">
                                    <div className="mb-5 flex items-center justify-between">
                                        <span className="text-xs font-medium text-muted-foreground">Access policy</span>
                                        <LockKeyhole
                                            className="size-4 text-muted-foreground"
                                            aria-hidden="true"
                                            strokeWidth={1.5}
                                        />
                                    </div>
                                    <p className="text-lg font-semibold tracking-tight">{authLabel}</p>
                                    <p className="mt-1 text-xs text-muted-foreground">
                                        {backend.authRequired === true
                                            ? "Bearer token required"
                                            : backend.authRequired === false
                                              ? "Authentication disabled"
                                              : "Reported by the backend"}
                                    </p>
                                </section>
                            </div>
                            <section className="mt-6 rounded-xl border border-border bg-card">
                                <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
                                    <div className="flex items-center gap-2">
                                        <Terminal
                                            className="size-4 text-muted-foreground"
                                            aria-hidden="true"
                                            strokeWidth={1.5}
                                        />
                                        <h2 className="text-sm font-semibold">Runtime connection</h2>
                                    </div>
                                    <Badge variant="outline">Loopback only</Badge>
                                </header>
                                <div className="flex flex-col gap-4 p-5">
                                    <div className="flex flex-wrap items-center justify-between gap-3">
                                        <code className="break-all text-sm text-muted-foreground">
                                            {backend.url ?? "Waiting for the local endpoint…"}
                                        </code>
                                        <span className="text-xs text-muted-foreground">
                                            {lastCheckedAt === null
                                                ? "No response yet"
                                                : `Checked ${new Date(lastCheckedAt).toLocaleTimeString()}`}
                                        </span>
                                    </div>
                                    {backend.error && (
                                        <p
                                            role="alert"
                                            className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive-foreground">
                                            {backend.error}
                                        </p>
                                    )}
                                    <div className="flex flex-wrap items-center gap-2">
                                        <RefreshSidecarButton
                                            isChecking={isChecking}
                                            onRefresh={() => void refresh()}
                                        />
                                        <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            onClick={() => setEventsOpen(true)}>
                                            <Activity aria-hidden="true" />
                                            Inspect events
                                        </Button>
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => navigateTo("settings")}>
                                            Connection settings
                                            <ArrowUpRight aria-hidden="true" />
                                        </Button>
                                    </div>
                                </div>
                            </section>
                            <div className="mt-6 grid gap-4 sm:grid-cols-2">
                                <button
                                    type="button"
                                    onClick={() => navigateTo("jobs")}
                                    className="workspace-link flex items-center gap-4 rounded-xl border border-border bg-card p-5 text-left">
                                    <FolderClock
                                        className="size-5 shrink-0 text-primary"
                                        aria-hidden="true"
                                        strokeWidth={1.5}
                                    />
                                    <span className="flex flex-1 flex-col gap-1">
                                        <span className="text-sm font-semibold">Conversion jobs</span>
                                        <span className="text-xs text-muted-foreground">
                                            A home for your document workflows.
                                        </span>
                                    </span>
                                    <ArrowUpRight
                                        className="size-4 text-muted-foreground"
                                        aria-hidden="true"
                                        strokeWidth={1.5}
                                    />
                                </button>
                                <button
                                    type="button"
                                    onClick={() => navigateTo("explorer")}
                                    className="workspace-link flex items-center gap-4 rounded-xl border border-border bg-card p-5 text-left">
                                    <Compass
                                        className="size-5 shrink-0 text-primary"
                                        aria-hidden="true"
                                        strokeWidth={1.5}
                                    />
                                    <span className="flex flex-1 flex-col gap-1">
                                        <span className="text-sm font-semibold">Corpus explorer</span>
                                        <span className="text-xs text-muted-foreground">
                                            Make room for a closer reading.
                                        </span>
                                    </span>
                                    <ArrowUpRight
                                        className="size-4 text-muted-foreground"
                                        aria-hidden="true"
                                        strokeWidth={1.5}
                                    />
                                </button>
                            </div>
                        </TabsContent>
                        <TabsContent value="jobs">
                            <PanelHeading
                                eyebrow="Document workflows"
                                title="Conversion jobs">
                                A dedicated view for document conversions and their results.
                            </PanelHeading>
                            <section className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card p-8 text-center">
                                <FolderClock
                                    className="mb-2 size-8 text-muted-foreground"
                                    aria-hidden="true"
                                    strokeWidth={1.5}
                                />
                                <h2 className="text-base font-semibold">Your job workspace</h2>
                                <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
                                    Job submission and tracking are not connected to this view yet. Backend availability
                                    is shown in the status bar below.
                                </p>
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setEventsOpen(true)}>
                                    Inspect backend connection
                                </Button>
                            </section>
                        </TabsContent>
                        <TabsContent value="explorer">
                            <PanelHeading
                                eyebrow="Texts & collections"
                                title="Corpus explorer">
                                A dedicated space to inspect the structure and content of your corpora.
                            </PanelHeading>
                            <section className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card p-8 text-center">
                                <Compass
                                    className="mb-2 size-8 text-muted-foreground"
                                    aria-hidden="true"
                                    strokeWidth={1.5}
                                />
                                <h2 className="text-base font-semibold">A place for your texts</h2>
                                <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
                                    Library browsing is not connected to this view yet. No collections have been loaded
                                    or counted.
                                </p>
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => navigateTo("dashboard")}>
                                    Back to dashboard
                                </Button>
                            </section>
                        </TabsContent>
                        <TabsContent value="settings">
                            <PanelHeading
                                eyebrow="Workspace preferences"
                                title="Settings">
                                Adjust the desktop appearance and inspect your local connection.
                            </PanelHeading>
                            <div className="flex flex-col gap-4">
                                <section className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card p-5">
                                    <div className="flex items-start gap-3">
                                        <Monitor
                                            className="mt-0.5 size-4 text-muted-foreground"
                                            aria-hidden="true"
                                            strokeWidth={1.5}
                                        />
                                        <div className="flex flex-col gap-1">
                                            <h2 className="text-sm font-semibold">Appearance</h2>
                                            <p className="text-sm capitalize text-muted-foreground">
                                                {theme} theme{theme === "system" ? ` · currently ${resolvedTheme}` : ""}
                                            </p>
                                            <p className="text-xs text-muted-foreground">
                                                Cycle system, light, and dark. Your preference is saved on this device.
                                            </p>
                                        </div>
                                    </div>
                                    <ThemeToggle />
                                </section>
                                <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-5">
                                    <div className="flex items-start gap-3">
                                        <Radio
                                            className="mt-0.5 size-4 text-muted-foreground"
                                            aria-hidden="true"
                                            strokeWidth={1.5}
                                        />
                                        <div className="flex flex-col gap-1">
                                            <h2 className="text-sm font-semibold">Connection monitoring</h2>
                                            <p className="text-sm text-muted-foreground">
                                                {isActive
                                                    ? "Polling the sidecar every 3 seconds."
                                                    : "Status polling is paused."}
                                            </p>
                                            <p className="text-xs text-muted-foreground">
                                                Pausing checks does not stop Python or any conversion jobs.
                                            </p>
                                        </div>
                                    </div>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={isActive ? pause : resume}>
                                        {isActive ? "Pause checks" : "Resume checks"}
                                    </Button>
                                </section>
                                <section className="rounded-xl border border-border bg-card p-5">
                                    <h2 className="mb-3 text-sm font-semibold">Backend access</h2>
                                    <dl className="grid gap-3 text-sm sm:grid-cols-[8rem_1fr]">
                                        <dt className="text-muted-foreground">Endpoint</dt>
                                        <dd className="break-all font-mono">{backend.url ?? "Not available"}</dd>
                                        <dt className="text-muted-foreground">Authentication</dt>
                                        <dd>{authLabel}</dd>
                                    </dl>
                                    <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                                        Authentication is configured by the backend environment. Appearance and
                                        monitoring preferences do not change its security policy.
                                    </p>
                                </section>
                            </div>
                        </TabsContent>
                    </div>
                </main>
            </Tabs>
            {eventsOpen && (
                <ActivityPanel
                    events={events}
                    onClear={clearEvents}
                    onClose={closeEvents}
                />
            )}
            <StatusBar
                backend={backend}
                isPolling={isActive}
                isChecking={isChecking}
                onRefresh={() => void refresh()}
                responseTimeMs={responseTimeMs}
                lastCheckedAt={lastCheckedAt}
                eventCount={events.length}
                eventsOpen={eventsOpen}
                toggleRef={eventsToggle}
                onToggleEvents={() => (eventsOpen ? closeEvents() : setEventsOpen(true))}
            />
        </div>
    )
}

export default App
