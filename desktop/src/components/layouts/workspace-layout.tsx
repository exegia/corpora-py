import { useEffect, useLayoutEffect, useRef, type Dispatch, type ReactNode } from "react"
import { useAtom, useAtomValue, useSetAtom } from "jotai"
import { Group, Panel, Separator } from "motion-panels/react"
import { Columns2, PanelBottom, PanelLeft, PanelRight } from "lucide-react"
import { TitleBar } from "@/components/title-bar"
import { Button } from "@/components/ui/button"
import { WorkspacePanel } from "@/components/workspace-panel"
import { TabLayout } from "@/components/layouts/tab-layout"
import type { PanelPluginArea } from "@/lib/panel"
import type { WorkspaceAction, TWorkspaceGroupType, WorkspaceState, WorkspaceTab } from "@/lib/workspace-tabs"
import type { TabID } from "@/shared/navigation"
import {
    sidebarWidthAtom,
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
            className="min-h-0 min-w-0">
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

    useEffect(() => {
        if (workspace.activeGroup === "secondary") setSecondaryCollapsed(false)
    }, [workspace.activeGroup, workspace.groups.secondary.activeId, setSecondaryCollapsed])

    function changeSecondaryCollapsed(collapsed: boolean) {
        if (collapsed && secondaryPanel.current?.contains(document.activeElement)) secondaryToggle.current?.focus()
        setSecondaryCollapsed(collapsed)
    }
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
            {(
                [
                    // ["sidebar", sidebarCollapsed, PanelLeft],
                    // ["inspector", inspectorCollapsed, PanelRight],
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
            ))}
            <Button
                ref={secondaryToggle}
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={`${secondaryCollapsed ? "Show" : "Hide"} secondary editor`}
                aria-expanded={!secondaryCollapsed}
                aria-controls="workspace-secondary"
                onClick={() => changeSecondaryCollapsed(!secondaryCollapsed)}>
                <Columns2 aria-hidden="true" />
            </Button>
        </div>
    )
    return (
        <Group
            id="sidebar-workspace--inspector"
            className="row-span-full">
            <Panel
                pin
                id="sidebar-workspaces">
                <TitleBar onOpenSettings={() => onNavigate("settings")}>{titleBarActions()}</TitleBar>
                <Group
                    id="sidebar--workspace"
                    orientation="horizontal">
                    <Panel
                        id="sidebar"
                        size={sidebarWidth}
                        style={{ padding: 3 }}
                        defaultSize={236}
                        minSize={236}
                        animate={{ scale: 1 }}
                        initial={{ scale: 0.9 }}
                        maxSize="33%"
                        onSizeChange={setSidebarWidth}
                        collapsed={sidebarCollapsed}
                        onCollapsedChange={(collapsed) =>
                            panelAction({ type: "set-open", area: "sidebar", open: !collapsed })
                        }
                        keepMounted>
                        <PanelVisibility
                            area="sidebar"
                            collapsed={sidebarCollapsed}
                        />
                    </Panel>
                    <Separator className={SEPARATOR} />
                    <Panel
                        animate={{ scale: 1 }}
                        initial={{ scale: 0.95 }}
                        pin
                        style={{ padding: 3 }}
                        className="bg-background rounded-xl"
                        id="workspace">
                        <Group
                            id="workspace-split"
                            // className="bg-background rounded-xl"
                            orientation="horizontal">
                            <Panel
                                animate={{ scale: 1 }}
                                initial={{ scale: 0.95 }}
                                pin
                                id="workspace-primary">
                                <section
                                    aria-label="Primary editor group"
                                    className="min-h-0 min-w-0">
                                    {editor("primary")}
                                </section>
                            </Panel>
                            <Separator className={SEPARATOR} />
                            <Panel
                                animate={{ scale: 1 }}
                                initial={{ scale: 0.95 }}
                                id="workspace-secondary">
                                <Group
                                    id="workspace-secondary--dock"
                                    orientation="vertical">
                                    <Panel
                                        pin
                                        animate={{ scale: 1 }}
                                        initial={{ scale: 0.95 }}
                                        id="workspace-secondary--panel">
                                        <section
                                            aria-label="Secondary editor group"
                                            className="min-h-0 min-w-0">
                                            {editor("secondary")}
                                        </section>
                                    </Panel>
                                    <Separator className={SEPARATOR} />
                                    <Panel
                                        id="workspace-secondary--dock"
                                        size={dockHeight}

                                        animate={{ scale: 1 }}
                                        initial={{ scale: 0.95 }}
                                        minSize={200}
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
                                            aria-label="Secondary editor group"
                                        />
                                    </Panel>
                                </Group>
                            </Panel>
                        </Group>
                    </Panel>
                </Group>
            </Panel>
            <Separator className={SEPARATOR} />
            <Panel
                id="inspector"
                size={inspectorWidth}
                animate={{ scale: 1 }}
                initial={{ scale: 0.9 }}
                defaultSize={352}
                minSize={236}
                maxSize="30%"
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
    )
}
