import { Button } from "@/components"
import { PanelHeading } from "@/components/heading"
import { RefreshSidecarButton } from "@/components/refresh-sidecar-button"
import { Badge } from "@/components/reui/badge"
import { TabsContent } from "@/components/ui/tabs"
import { Activity, ArrowUpRight, Database, LockKeyhole, Radio, Terminal } from "lucide-react"

export const HomeTab = () => {
    return (
        <TabsContent value="dashboard">
            <PanelHeading
                eyebrow="Workspace overview"
                title="Your corpus workspace.">
                Convert, inspect, and work with your texts. A managed Python runtime keeps the backend close to your
                desktop.
            </PanelHeading>
            <div className="grid gap-4 sm:grid-cols-3">
                <section className="rounded-xl border border-border bg-card p-5">
                    <div className="mb-5 flex items-center justify-between">
                        <span className="text-xs font-medium text-muted-foreground">Python runtime</span>
                        <Database
                            className="size-4 text-muted-foreground"
                            aria-hidden="true"
                            strokeWidth={1.5}
                        />
                    </div>
                    {/*<p className="text-lg font-semibold capitalize tracking-tight">{backend.state}</p>*/}
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
                    {/*<p className="text-lg font-semibold tabular-nums tracking-tight">
                      {responseTimeMs === null ? "—" : `${responseTimeMs} ms`}
                  </p>*/}
                    {/*<p className="mt-1 text-xs text-muted-foreground">
                      {isActive
                          ? "Retrying while offline · every 3 seconds"
                          : backend.state === "ready"
                            ? "Online · automatic checks stopped"
                            : "Automatic checks paused"}
                  </p>*/}
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
                            {/*{backend.url ?? "Waiting for the local endpoint…"}*/}
                        </code>
                        {/*<span className="text-xs text-muted-foreground">
                          {lastCheckedAt === null
                              ? "No response yet"
                              : `Checked ${new Date(lastCheckedAt).toLocaleTimeString()}`}
                      </span>*/}
                    </div>
                    {/*{backend.error && (
                      <p
                          role="alert"
                          className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive-foreground">
                          {backend.error}
                      </p>
                  )}*/}
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
                        <span className="text-xs text-muted-foreground">A home for your document workflows.</span>
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
                        <span className="text-xs text-muted-foreground">Make room for a closer reading.</span>
                    </span>
                    <ArrowUpRight
                        className="size-4 text-muted-foreground"
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                </button>
            </div>
        </TabsContent>
    )
}
