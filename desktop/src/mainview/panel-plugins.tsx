import { useAtomValue, useSetAtom } from "jotai"
import { ActivityPanel } from "@/components/activity-panel"
import { ConversionLogs } from "@/components/conversion-logs"
import { ConversionJobStatus, conversionDate } from "@/components/conversion-job-status"
import { RefreshSidecarButton } from "@/components/refresh-sidecar-button"
import { Button } from "@/components/ui/button"
import { panelPluginRegistry, type IPanelPluginProps } from "@/lib/panel"
import { jobWorkspaceTab } from "@/lib/workspace-tabs"
import { navigationTab } from "@/shared/navigation"
import {
    backendAtom,
    backendControllerAtom,
    backendEventsAtom,
    backendSnapshotAtom,
    clearBackendEventsAtom,
    conversionSnapshotAtom,
    inspectedJobIdAtom,
    panelActionAtom,
    selectedJobAtom,
    workspaceActionAtom
} from "@/shared/store"

function NavigationPlugin() {
    const dispatch = useSetAtom(workspaceActionAtom)
    return (
        <nav
            className="flex flex-col gap-1"
            aria-label="Workspace tools">
            <Button
                type="button"
                variant="ghost"
                size="sm"
                className="justify-start"
                onClick={() => dispatch({ type: "open", tab: navigationTab("jobs") })}>
                Conversion jobs
            </Button>
        </nav>
    )
}

function RecentJobsPlugin() {
    const { jobs } = useAtomValue(conversionSnapshotAtom)
    const selected = useAtomValue(selectedJobAtom)
    const dispatch = useSetAtom(workspaceActionAtom)
    const inspect = useSetAtom(inspectedJobIdAtom)
    const activeCount = jobs.filter((job) => job.status === "queued" || job.status === "running").length
    return (
        <div className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">{activeCount} active</p>
            {jobs.length ? (
                <ul className="flex flex-col gap-1">
                    {jobs.slice(0, 10).map((job) => (
                        <li key={job.id}>
                            <button
                                type="button"
                                className="workspace-link flex w-full min-w-0 flex-col gap-1 rounded-lg p-2 text-start"
                                aria-pressed={selected?.id === job.id}
                                onClick={() => {
                                    inspect(job.id)
                                    dispatch({ type: "open", tab: jobWorkspaceTab(job) })
                                }}>
                                <span
                                    className="w-full truncate text-xs font-medium"
                                    title={job.display_name || job.name}>
                                    {job.display_name || job.name}
                                </span>
                                <span className="text-[11px] capitalize text-muted-foreground">
                                    {job.status} · {job.source_format}
                                </span>
                            </button>
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="text-xs text-muted-foreground">
                    Create a conversion in Jobs. Its progress continues in the background.
                </p>
            )}
        </div>
    )
}

function JobInspectorPlugin() {
    const job = useAtomValue(selectedJobAtom)
    return job ? (
        <div className="flex flex-col gap-3 text-xs">
            <h3 className="break-words text-sm font-semibold">{job.display_name || job.name}</h3>
            <ConversionJobStatus status={job.status} />
            <dl className="flex flex-col gap-2">
                <div>
                    <dt className="text-muted-foreground">Source → output</dt>
                    <dd>
                        {job.source_format} → .{job.output_format}
                    </dd>
                </div>
                <div>
                    <dt className="text-muted-foreground">Submitted</dt>
                    <dd>{conversionDate(job.created_at)}</dd>
                </div>
                <div>
                    <dt className="text-muted-foreground">Job ID</dt>
                    <dd className="select-text break-all font-mono">{job.id}</dd>
                </div>
            </dl>
            <h4 className="font-semibold">Pipeline</h4>
            <ol className="flex flex-col gap-2">
                {job.steps.map((step) => (
                    <li
                        key={step.id}
                        className="flex flex-wrap justify-between gap-1">
                        <span>{step.title}</span>
                        <span className="text-muted-foreground">{step.status}</span>
                    </li>
                ))}
            </ol>
            {job.error && <p className="break-words text-destructive-foreground">{job.error}</p>}
        </div>
    ) : (
        <p className="text-xs text-muted-foreground">Open a conversion job to inspect its pipeline.</p>
    )
}

function BackendInspectorPlugin() {
    const backend = useAtomValue(backendAtom)
    const { isChecking } = useAtomValue(backendSnapshotAtom)
    const controller = useAtomValue(backendControllerAtom)
    return (
        <div className="flex flex-col gap-3 text-xs">
            <dl className="flex flex-col gap-2">
                <div>
                    <dt className="text-muted-foreground">Status</dt>
                    <dd className="capitalize">{backend.state}</dd>
                </div>
                <div>
                    <dt className="text-muted-foreground">Endpoint</dt>
                    <dd className="select-text break-all font-mono">{backend.url ?? "Waiting for Python"}</dd>
                </div>
                <div>
                    <dt className="text-muted-foreground">Access</dt>
                    <dd>
                        {backend.authRequired === null
                            ? "Awaiting policy"
                            : backend.authRequired
                              ? "JWT protected"
                              : "Local development"}
                    </dd>
                </div>
            </dl>
            <RefreshSidecarButton
                isChecking={isChecking}
                onRefresh={() => void controller.refresh()}
            />
        </div>
    )
}

function EventsPlugin({ id }: IPanelPluginProps) {
    const events = useAtomValue(backendEventsAtom)
    const clear = useSetAtom(clearBackendEventsAtom)
    const dispatch = useSetAtom(panelActionAtom)
    return (
        <ActivityPanel
            events={events}
            onClear={clear}
            onClose={() => dispatch({ type: "close", id })}
        />
    )
}

function LogsPlugin({ id }: IPanelPluginProps) {
    const job = useAtomValue(selectedJobAtom)
    // The stable plugin ID is the state scope even when this component moves between React parents.
    return job ? (
        <ConversionLogs
            scope={id}
            job={job}
            stage={null}
            onClearStage={() => {}}
        />
    ) : (
        <p className="text-xs text-muted-foreground">Open a conversion job to inspect its detailed logs.</p>
    )
}

for (const definition of [
    { id: "sidebar-navigation", name: "Navigation", area: "sidebar", component: NavigationPlugin },
    { id: "sidebar-jobs", name: "Recent jobs", area: "sidebar", component: RecentJobsPlugin },
    { id: "inspector-job", name: "Job inspector", area: "inspector", component: JobInspectorPlugin },
    { id: "inspector-backend", name: "Python sidecar", area: "inspector", component: BackendInspectorPlugin },
    { id: "dock-events", name: "Connection events", area: "dock", component: EventsPlugin },
    { id: "dock-logs", name: "Job logs", area: "dock", component: LogsPlugin }
] as const)
    panelPluginRegistry.registerPlugin(definition)
