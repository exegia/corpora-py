import { useEffect, useRef } from "react"
import { useAtomValue, useSetAtom } from "jotai"
import useBackend from "@/hooks/use-backend"
import { useBackendEvents } from "@/hooks/use-backend-events"
import { useConversionJobs } from "@/hooks/use-conversion-jobs"
import { useTabs } from "@/hooks/use-tabs"
import { useTheme } from "@/hooks/use-theme"
import { WorkspaceLayout } from "@/components/layouts/workspace-layout"
import { StatusBar } from "@/components/status-bar"
import { activeWorkspaceTab, jobWorkspaceTab, type WorkspaceTab } from "@/lib/workspace-tabs"
import { navigationTab, type TabID } from "@/shared/navigation"
import type { ConversionJob } from "@/shared/conversion"
import { eventsOpenAtom, inspectedJobIdAtom, panelActionAtom, showEventsAtom } from "@/shared/store"
import "./panel-plugins"

function App() {
    // Only App owns controller subscriptions: plugin folds, removal and moves cannot stop them.
    const monitor = useBackend()
    const { backend, isActive, isAutoEnabled, isChecking, pause, resume, refresh, lastCheckedAt, responseTimeMs } =
        monitor
    const conversions = useConversionJobs()
    const { events } = useBackendEvents(backend)
    const appearance = useTheme()
    const { workspace, dispatch } = useTabs()
    const inspect = useSetAtom(inspectedJobIdAtom)
    const panelAction = useSetAtom(panelActionAtom)
    const eventsOpen = useAtomValue(eventsOpenAtom)
    const showEvents = useSetAtom(showEventsAtom)
    const eventsToggle = useRef<HTMLButtonElement>(null)
    const current = activeWorkspaceTab(workspace)

    useEffect(() => {
        if (current?.jobId) {
            inspect(current.jobId)
            panelAction({ type: "open", id: "dock-logs" })
        }
    }, [current?.jobId, inspect, panelAction])

    function focusTab(id: string) {
        requestAnimationFrame(() =>
            document.querySelector<HTMLButtonElement>(`[data-workspace-tab-id="${CSS.escape(id)}"]`)?.focus()
        )
    }
    function navigateTo(id: TabID) {
        const tab = navigationTab(id)
        dispatch({ type: "open", target: "primary", tab })
        focusTab(tab.id)
    }
    function openJob(job: ConversionJob) {
        inspect(job.id)
        dispatch({ type: "open", tab: jobWorkspaceTab(job) })
        focusTab(`job:${job.id}`)
    }
    function renderTab(tab: WorkspaceTab) {
        const View = tab.view
        return (
            <View
                backend={backend}
                conversions={conversions}
                jobId={tab.jobId}
                isActive={isActive}
                isAutoEnabled={isAutoEnabled}
                isChecking={isChecking}
                responseTimeMs={responseTimeMs}
                lastCheckedAt={lastCheckedAt}
                onRefresh={() => void refresh()}
                onShowEvents={showEvents}
                onNavigate={navigateTo}
                onOpenJob={openJob}
                pause={pause}
                resume={resume}
                {...appearance}
            />
        )
    }
    return (
        <div className="motion-workspace flex h-dvh min-h-0 flex-col gap-1">
            <WorkspaceLayout
                workspace={workspace}
                dispatch={dispatch}
                renderTab={renderTab}
                onNavigate={navigateTo}
            />
            <StatusBar
                backend={backend}
                isPolling={isActive}
                isAutoEnabled={isAutoEnabled}
                isChecking={isChecking}
                onRefresh={() => void refresh()}
                responseTimeMs={responseTimeMs}
                lastCheckedAt={lastCheckedAt}
                eventCount={events.length}
                eventsOpen={eventsOpen}
                toggleRef={eventsToggle}
                onToggleEvents={() => {
                    if (eventsOpen) panelAction({ type: "close", id: "dock-events" })
                    else showEvents()
                }}
            />
        </div>
    )
}

export default App
