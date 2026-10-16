import { useLayoutEffect, useRef, type Dispatch, type ReactNode } from "react"
import { useAtom, useAtomValue, useSetAtom } from "jotai"
import { Group, Panel, Separator } from "motion-panels/react"
import { Columns2 } from "lucide-react"
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
    sidebarWidthAtom,
    inspectorWidthAtom,
    secondaryWidthAtom,
    dockHeightAtom,
    sidebarCollapsedAtom,
    inspectorCollapsedAtom,
    dockCollapsedAtom,
    secondaryCollapsedAtom,
    panelActionAtom,
    PANEL_MIN_WIDTH
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
    const [sidebarWidth, setSidebarWidth] = useAtom(sidebarWidthAtom)
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
            <TabLayout
                group={group}
                workspace={workspace}
                dispatch={dispatch}
                renderTab={renderTab}
                onRevealGroup={(target) => {
                    if (target === "secondary") setSecondaryCollapsed(false)
                }}
                onNewConversion={() => onNavigate("jobs")}
            />
        )
    }
    const titleBarActions = () => (
        <div className="flex gap-2">
            {/*{(
                [
                    ["sidebar", sidebarCollapsed, PanelLeft],
                    ["inspector", inspectorCollapsed, PanelRight],
                    ["dock", dockCollapsed, PanelBottom]
                ] as const
            ).map(([area, collapsed, Icon]) => (
                <Button
                    key={area}
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    data-panel-toggle={area}
                    aria-label={`${collapsed ? "Show" : "Hide"} ${area}`}
                    aria-expanded={!collapsed}
                    aria-controls={`workspace-${area}`}
                    onClick={() => panelAction({ type: "toggle", area })}>
                    <Icon aria-hidden="true" />
                </Button>
            ))}*/}
            <Button
                ref={secondaryToggle}
                type="button"
                variant="ghost"
                size="icon-sm"
                data-secondary-toggle
                disabled={secondaryEmpty || navigationActive}
                aria-label={`${secondaryHidden ? "Show" : "Hide"} secondary editor`}
                aria-expanded={!secondaryHidden}
                aria-controls="workspace-secondary"
                onClick={() => setSecondaryCollapsed(!secondaryCollapsed)}>
                <Columns2 aria-hidden="true" />
            </Button>
        </div>
    )

    const renderTitleNavigation = () => (
        <TitleBar onOpenSettings={() => onNavigate("settings")}>{titleBarActions()}</TitleBar>
    )

    const renderSidebar = () => (
        <Panel
            id="sidebar"
            size={sidebarWidth}
            defaultSize={PANEL_DEFAULT_WIDTH}
            minSize={PANEL_MIN_WIDTH}
            maxSize={PANEL_DEFAULT_WIDTH}
            style={{ padding: 2 }}
            animate={{ scale: 1 }}

            initial={{ scale: 0.95 }}
            onSizeChange={setSidebarWidth}
            //    collapsed={sidebarCollapsed}
            onCollapsedChange={(collapsed) => panelAction({ type: "set-open", area: "sidebar", open: !collapsed })}
            keepMounted>
            <PanelVisibility
                area="sidebar"
                collapsed={sidebarCollapsed}
            />
        </Panel>
    )

    return (
        <div className="flex h-full flex-1 min-h-0 flex-col">
            {renderTitleNavigation()}
            <Group
                id="sidebar-workspace-inspector"
                className="min-h-0 flex-1 size-full">
                {renderSidebar()}
                <Panel
                    pin
                    id="sidebar-workspaces">
                    <div className="flex h-full min-h-0 flex-col">
                        <div className="min-h-0 flex-1">
                            <Group
                                id="sidebar--workspace"
                                orientation="horizontal">
                                <Separator
                                    aria-label="Resize sidebar"
                                    className={SEPARATOR}
                                />
                                <Panel
                                    pin
                                    id="workspace"
                                    style={{ padding: 3 }}
                                    className="rounded-xl bg-background">
                                    <Group orientation="vertical">
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
