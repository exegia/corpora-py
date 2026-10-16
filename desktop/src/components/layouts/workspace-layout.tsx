import { useLayoutEffect, useRef, type Dispatch, type ReactNode } from "react"
import { useAtom, useAtomValue, useSetAtom } from "jotai"
import { Group, Panel, Separator } from "motion-panels/react"
import { Columns2, PanelLeft, PanelRight } from "lucide-react"
import { TitleBar } from "@/components/title-bar"
import { Button } from "@/components/ui/button"
import { WorkspacePanel } from "@/components/workspace-panel"
import { TabLayout } from "@/components/layouts/tab-layout"
import type { PanelPluginArea } from "@/lib/panel"
import {
    activeWorkspaceTab,
    isTopNavigationTab,
    type WorkspaceAction,
    type TWorkspaceGroupType,
    type WorkspaceState,
    type WorkspaceTab
} from "@/lib/workspace-tabs"
import type { TabID } from "@/shared/navigation"
import {
    PANEL_DEFAULT_WIDTH,
    sidebarPanelWidthAtom,
    inspectorWidthAtom,
    secondaryWidthAtom,
    dockHeightAtom,
    sidebarCollapsedAtom,
    inspectorCollapsedAtom,
    dockCollapsedAtom,
    secondaryCollapsedAtom,
    panelActionAtom
} from "@/shared/store"

interface WorkspaceLayoutProps {
    workspace: WorkspaceState
    dispatch: Dispatch<WorkspaceAction>
    renderTab: (tab: WorkspaceTab) => ReactNode
    onNavigate: (id: TabID) => void
}

function PanelVisibility({ area, collapsed }: { area: PanelPluginArea; collapsed: boolean }) {
    const panel = useRef<HTMLElement>(null)
    // Covers atom-driven closures as well as titlebar and drag/keyboard folds.
    useLayoutEffect(() => {
        if (collapsed && panel.current?.contains(document.activeElement)) {
            document.querySelector<HTMLButtonElement>(`[data-panel-toggle="${area}"]`)?.focus()
        }
    }, [area, collapsed])
    return (
        <section
            ref={panel}
            id={`workspace-${area}`}
            inert={collapsed}
            aria-label={`${area} panel`}
            className="h-full min-h-0 min-w-0">
            <WorkspacePanel area={area} />
        </section>
    )
}

export const SEPARATOR =
    "z-10 flex items-center justify-center rounded-full outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 after:bg-muted-foreground/45 after:opacity-0 after:transition after:duration-150 after:content-[''] hover:after:bg-muted-foreground hover:after:opacity-100 focus-visible:after:bg-foreground focus-visible:after:opacity-100 active:after:bg-foreground aria-[orientation=horizontal]:h-3.5 aria-[orientation=vertical]:w-3.5 aria-[orientation=horizontal]:after:h-0.5 aria-[orientation=horizontal]:after:w-[calc(100%-20px)] aria-[orientation=vertical]:after:h-[calc(100%-20px)] aria-[orientation=vertical]:after:w-0.5 data-crossing:after:bg-muted-foreground data-crossing:after:opacity-100 data-resizing:after:bg-foreground data-resizing:after:opacity-100"

export function WorkspaceLayout({ workspace, dispatch, renderTab, onNavigate }: WorkspaceLayoutProps) {
    const sidebarWidth = useAtomValue(sidebarPanelWidthAtom)
    const [inspectorWidth, setInspectorWidth] = useAtom(inspectorWidthAtom)
    const [secondaryWidth, setSecondaryWidth] = useAtom(secondaryWidthAtom)
    const [dockHeight, setDockHeight] = useAtom(dockHeightAtom)
    const sidebarCollapsed = useAtomValue(sidebarCollapsedAtom)
    const inspectorCollapsed = useAtomValue(inspectorCollapsedAtom)
    const dockCollapsed = useAtomValue(dockCollapsedAtom)
    const [secondaryCollapsed, setSecondaryCollapsed] = useAtom(secondaryCollapsedAtom)
    const panelAction = useSetAtom(panelActionAtom)
    const secondaryPanel = useRef<HTMLElement>(null)
    const secondaryToggle = useRef<HTMLButtonElement>(null)
    const primaryTab = activeWorkspaceTab(workspace, "primary")
    const navigationActive = workspace.activeGroup === "primary" && !!primaryTab && isTopNavigationTab(primaryTab)
    const secondaryEmpty = workspace.groups.secondary.tabs.length === 0
    const secondaryHidden = navigationActive || secondaryEmpty || secondaryCollapsed

    useLayoutEffect(() => {
        if (secondaryHidden && secondaryPanel.current?.contains(document.activeElement))
            secondaryToggle.current?.focus()
    }, [secondaryHidden])

    function editor(group: TWorkspaceGroupType) {
        return (
            <TabLayout group={group} workspace={workspace} dispatch={dispatch} renderTab={renderTab} />
        )
    }
    const selectedTab = activeWorkspaceTab(workspace)
    const canSplit = !!selectedTab && !selectedTab.pinned && !isTopNavigationTab(selectedTab)
    const renderEditorControls = () => (
        <div className="flex h-8 shrink-0 items-center justify-end gap-1 px-2" role="toolbar" aria-label="Workspace controls">
            <Button
                ref={secondaryToggle}
                type="button"
                variant="ghost"
                size="icon-sm"
                data-secondary-toggle
                disabled={secondaryEmpty && !canSplit}
                aria-label={secondaryEmpty ? "Split editor" : `${secondaryHidden ? "Show" : "Hide"} secondary editor`}
                aria-expanded={!secondaryHidden}
                aria-controls="workspace-secondary"
                onClick={() => {
                    if (secondaryEmpty && canSplit) {
                        dispatch({ type: "move", group: workspace.activeGroup, tabId: selectedTab.id, target: "secondary" })
                        setSecondaryCollapsed(false)
                    } else if (secondaryHidden) {
                        const tabId = workspace.groups.secondary.activeId
                        if (tabId) dispatch({ type: "select", group: "secondary", tabId })
                        setSecondaryCollapsed(false)
                    } else {
                        dispatch({ type: "focus", group: "primary" })
                        setSecondaryCollapsed(true)
                    }
                }}>
                <Columns2 aria-hidden="true" />
            </Button>
            {inspectorCollapsed && (
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    data-panel-toggle="inspector"
                    aria-label="Show inspector"
                    aria-expanded={false}
                    aria-controls="workspace-inspector"
                    onClick={() => panelAction({ type: "set-open", area: "inspector", open: true })}>
                    <PanelRight aria-hidden="true" />
                </Button>
            )}
        </div>
    )

    const renderTitleNavigation = () => (
        <TitleBar onOpenSettings={() => onNavigate("settings")} />
    )

    const renderSidebar = () => (
        <Panel
            id="sidebar"
            size={sidebarWidth}
            defaultSize={PANEL_DEFAULT_WIDTH}
            minSize={sidebarWidth}
            maxSize={sidebarWidth}
            style={{ padding: 2 }}
            animate={{ scale: 1 }}
            initial={{ scale: 0.95 }}
            keepMounted>
            <div hidden={!sidebarCollapsed} className={sidebarCollapsed ? "flex h-full justify-center pt-2" : "hidden"} aria-label="Collapsed sidebar">
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    data-panel-toggle="sidebar"
                    aria-label="Expand sidebar"
                    aria-expanded={false}
                    aria-controls="workspace-sidebar"
                    onClick={() => panelAction({ type: "set-open", area: "sidebar", open: true })}>
                    <PanelLeft aria-hidden="true" />
                </Button>
            </div>
            <div hidden={sidebarCollapsed} className="h-full min-h-0">
                <PanelVisibility area="sidebar" collapsed={sidebarCollapsed} />
            </div>
        </Panel>
    )

    return (
        <div className="flex h-full flex-1 min-h-0 flex-col">
            {renderTitleNavigation()}
            <Group
                id="sidebar-workspace-inspector"
                className="min-h-0 flex-1 size-full">
                {renderSidebar()}
                {/* Explicitly suppress the implicit edge grip for this fixed-width panel. */}
                <Separator aria-hidden="true" tabIndex={-1} style={{ display: "none" }} />
                <Panel
                    pin
                    id="sidebar-workspaces">
                    <div className="flex h-full min-h-0 flex-col">
                        <div className="min-h-0 flex-1">
                            <Group
                                id="sidebar--workspace"
                                orientation="horizontal">
                                <Panel
                                    pin
                                    id="workspace"
                                    style={{ padding: 3 }}
                                    className="workspace-surface rounded-xl bg-background">
                                    <div className="flex h-full min-h-0 flex-col">
                                        {renderEditorControls()}
                                        <Group orientation="vertical" className="min-h-0 flex-1">
                                            <Panel pin>
                                                <Group
                                                    id="workspace-split"
                                                    orientation="horizontal">
                                                    <Panel
                                                        pin
                                                        id="workspace-primary">
                                                        <section
                                                            aria-label="Primary editor group"
                                                            className="h-full min-h-0 min-w-0">
                                                            {editor("primary")}
                                                        </section>
                                                    </Panel>
                                                    <Separator
                                                        aria-label="Resize secondary editor"
                                                        className={SEPARATOR}
                                                    />
                                                    <Panel
                                                        id="workspace-secondary"
                                                        size={secondaryWidth}
                                                        defaultSize="45%"
                                                        minSize={160}
                                                        maxSize="70%"
                                                        onSizeChange={setSecondaryWidth}
                                                        collapsed={secondaryHidden}
                                                        onCollapsedChange={(collapsed) => {
                                                            if (!secondaryEmpty && !navigationActive)
                                                                setSecondaryCollapsed(collapsed)
                                                        }}
                                                        keepMounted>
                                                        <section
                                                            ref={secondaryPanel}
                                                            inert={secondaryHidden}
                                                            aria-label="Secondary editor group"
                                                            className="h-full min-h-0 min-w-0">
                                                            {editor("secondary")}
                                                        </section>
                                                    </Panel>
                                                </Group>
                                            </Panel>
                                            <Separator
                                                aria-label="Resize dock"
                                                className={SEPARATOR}
                                            />
                                            <Panel
                                                id="workspace-dock-container"
                                                size={dockHeight}
                                                defaultSize={210}
                                                minSize={110}
                                                maxSize="65%"
                                                onSizeChange={setDockHeight}
                                                collapsed={dockCollapsed}
                                                onCollapsedChange={(collapsed) =>
                                                    panelAction({ type: "set-open", area: "dock", open: !collapsed })
                                                }
                                                keepMounted>
                                                <PanelVisibility
                                                    area="dock"
                                                    collapsed={dockCollapsed}
                                                />
                                            </Panel>
                                        </Group>
                                    </div>
                                </Panel>
                            </Group>
                        </div>
                    </div>
                </Panel>
                <Separator
                    aria-label="Resize inspector"
                    className={SEPARATOR}
                />
                <Panel
                    id="inspector"
                    size={inspectorWidth}
                    defaultSize={PANEL_DEFAULT_WIDTH}
                    minSize={200}
                    maxSize={640}
                    animate={{ scale: 1 }}
                    initial={{ scale: 0.9 }}
                    onSizeChange={setInspectorWidth}
                    collapsed={inspectorCollapsed}
                    onCollapsedChange={(collapsed) =>
                        panelAction({ type: "set-open", area: "inspector", open: !collapsed })
                    }
                    keepMounted>
                    <PanelVisibility
                        area="inspector"
                        collapsed={inspectorCollapsed}
                    />
                </Panel>
            </Group>
        </div>
    )
}
