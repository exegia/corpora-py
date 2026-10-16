import { useEffect, useRef, type Dispatch, type ReactNode } from "react"
import { Pin, X } from "lucide"
import { ArrowLeftRight, MoreHorizontal, PinIcon, XIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { MorphIcon } from "morphicons/react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger
} from "@/components/ui/dropdown-menu"
import {
    workspaceReducer,
    isTopNavigationTab,
    type WorkspaceAction,
    type WorkspaceType,
    type WorkspaceState,
    type WorkspaceTab,
    TWorkspaceGroupType
} from "@/lib/workspace-tabs"
import { cn } from "tailwind-variants"

interface TabLayoutProps {
    group: TWorkspaceGroupType
    workspace: WorkspaceState
    dispatch: Dispatch<WorkspaceAction>
    renderTab: (tab: WorkspaceTab) => ReactNode
    onRevealGroup: (group: WorkspaceType) => void
    onNewConversion: () => void
}

export function TabLayout({ group, workspace, dispatch, renderTab, onRevealGroup, onNewConversion }: TabLayoutProps) {
    const { tabs: allTabs, activeId } = workspace.groups[group]
    const tabs = allTabs.filter((tab) => !isTopNavigationTab(tab))
    const navigationView = allTabs.find((tab) => tab.id === activeId && isTopNavigationTab(tab))
    const triggers = useRef<Record<string, HTMLButtonElement | null>>({})
    const menu = useRef<HTMLButtonElement | null>(null)
    const previous = useRef(activeId)
    const selected = tabs.find((tab) => tab.id === activeId)
    const target = group === "primary" ? "secondary" : "primary"

    useEffect(() => {
        if (previous.current !== activeId && workspace.activeGroup === group) {
            triggers.current[activeId ?? ""]?.focus()
        }
        previous.current = activeId
        triggers.current[activeId ?? ""]?.scrollIntoView({ block: "nearest", inline: "nearest" })
    }, [activeId, group, workspace.activeGroup])

    function select(tabId: string) {
        dispatch({ type: "select", group, tabId })
        triggers.current[tabId]?.focus()
    }
    function close(tabId: string) {
        const action: WorkspaceAction = { type: "close", group, tabId }
        const next = workspaceReducer(workspace, action)
        if (next === workspace) return
        dispatch(action)
        requestAnimationFrame(() => {
            const nextId = next.groups[group].activeId
            if (next.groups.secondary.tabs.length === 0 && group === "secondary") {
                document.querySelector<HTMLInputElement>('[data-top-navigation="tab:home"] input')?.focus()
            } else if (nextId && triggers.current[nextId]) triggers.current[nextId]?.focus()
            else document.querySelector<HTMLInputElement>('[data-top-navigation="tab:home"] input')?.focus()
        })
    }

    const renderTabsMenu = () => (
        <div className="absolute top-0 right-2">
            <DropdownMenu>
                <DropdownMenuTrigger
                    ref={menu}
                    render={
                        <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`${group === "primary" ? "Primary" : "Secondary"} tabs menu`}
                        />
                    }>
                    <MoreHorizontal aria-hidden="true" />
                </DropdownMenuTrigger>
                <DropdownMenuContent
                    align="end"
                    className="w-60">
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Open tabs</DropdownMenuLabel>
                        {tabs.length ? (
                            tabs.map((tab) => (
                                <DropdownMenuItem
                                    key={tab.id}
                                    onClick={() => select(tab.id)}>
                                    <span className="min-w-0 flex-1 truncate">{tab.title}</span>
                                    {tab.pinned && <PinIcon aria-hidden="true" />}
                                </DropdownMenuItem>
                            ))
                        ) : (
                            <DropdownMenuItem disabled>No open tabs</DropdownMenuItem>
                        )}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={onNewConversion}>Open conversion jobs</DropdownMenuItem>
                    <DropdownMenuItem
                        disabled={!selected || selected.pinned}
                        onClick={() => {
                            if (!selected || selected.pinned) return
                            onRevealGroup(target)
                            dispatch({ type: "move", group, tabId: selected.id, target })
                        }}>
                        <ArrowLeftRight aria-hidden="true" />
                        Move active tab to {target} group
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        disabled={!selected || selected.pinned}
                        onClick={() => {
                            if (selected) close(selected.id)
                        }}>
                        <XIcon aria-hidden="true" />
                        Close active tab
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )

    return (
        <>
            {navigationView && (
                <section className="@container h-full min-h-0 overflow-y-auto p-5">{renderTab(navigationView)}</section>
            )}
            <Tabs
                value={navigationView ? null : activeId}
                unmountOnExit={false}
                lazyMount
                onValueChange={({ value }) => {
                    if (value) dispatch({ type: "select", group, tabId: value })
                }}
                onFocusCapture={() => dispatch({ type: "focus", group })}
                className={navigationView ? "hidden" : "h-full min-h-0 min-w-0 gap-0"}
                data-workspace-group={group}>
                <div className="relative flex w-full shrink-0 items-center gap-0.5 px-2 pt-1.5 pr-10">
                    <TabsList
                        variant="glass"
                        aria-label={`${group === "primary" ? "Primary" : "Secondary"} workspace tabs`}>
                        {tabs.map((tab) => (
                            <div
                                key={tab.id}
                                className="relative flex shrink-0 items-center">
                                <TabsTrigger
                                    value={tab.id}
                                    title={tab.title}
                                    data-workspace-tab-id={tab.id}
                                    className={cn(tab.pinned ? "pr-4" : "pr-3", "py-3")}
                                    ref={(node) => {
                                        triggers.current[tab.id] = node
                                    }}
                                    onKeyDown={(event) => {
                                        if (event.key === "Delete" && !tab.pinned) {
                                            event.preventDefault()
                                            close(tab.id)
                                        }
                                    }}>
                                    <span className="max-w-44 min-h-16 truncate text-sm">{tab.title}</span>
                                </TabsTrigger>

                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-xs"
                                    className="absolute right-1 z-20 size-4"
                                    aria-label={`Close ${tab.title}`}
                                    onClick={() => close(tab.id)}>
                                    <MorphIcon
                                        icon={tab.pinned ? Pin : X}
                                        aria-hidden="true"
                                        className="size-2.5 text-secondary-foreground"
                                    />
                                </Button>
                            </div>
                        ))}
                    </TabsList>
                    {renderTabsMenu()}
                </div>
                {tabs.length
                    ? tabs.map((tab) => (
                          <TabsContent
                              key={tab.id}
                              value={tab.id}
                              className="min-h-0 min-w-0 data-[state=inactive]:hidden">
                              {renderTab(tab)}
                          </TabsContent>
                      ))
                    : null}
            </Tabs>
        </>
    )
}
