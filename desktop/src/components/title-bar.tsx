import type { ReactNode } from "react"
import { useAtom, useAtomValue, useSetAtom } from "jotai"
import { ChevronDown, X } from "lucide-react"
import Logo from "@/components/logo"
import { SettingsButton } from "./settings-button"
import { Button } from "./ui/shark-button"
import { Popover, PopoverDescription, PopoverPopup, PopoverTitle, PopoverTrigger } from "@/components/ui/popover"
import { SegmentGroup, SegmentGroupItem, SegmentGroupItemText } from "@/components/ui/segment-group"
import {
    activeTabAtom,
    resolvedThemeAtom,
    resetWorkspaceAtom,
    workspaceAtom,
    titlebarPopoverOpenAtom,
    workspaceActionAtom
} from "@/shared/store"

import { destinations, navigationTab } from "@/shared/navigation"
import { MorphIcon } from "morphicons/react"
import { isTopNavigationTab, workspaceReducer } from "@/lib/workspace-tabs"

export interface TitleBarProps {
    onOpenSettings: () => void
    children?: ReactNode
}

export function TitleBar({ onOpenSettings, children }: TitleBarProps) {
    const [menuOpen, setMenuOpen] = useAtom(titlebarPopoverOpenAtom)
    const workspace = useAtomValue(workspaceAtom)
    const editorTabs = Object.values(workspace.groups)
        .flatMap((group) => group.tabs)
        .filter((tab) => !isTopNavigationTab(tab))
    const items = [
        ...destinations.map((item) => ({ id: item.id, title: item.label, icon: item.icon, pinned: true })),
        ...editorTabs.map((tab) => ({ ...tab, icon: undefined }))
    ]
    const dispatch = useSetAtom(workspaceActionAtom)
    const activeId = useAtomValue(activeTabAtom)
    const resetWorkspace = useSetAtom(resetWorkspaceAtom)
    const theme = useAtomValue(resolvedThemeAtom)

    function close(tabId: string) {
        const group = workspace.groups.primary.tabs.some((tab) => tab.id === tabId) ? "primary" : "secondary"
        const action = { type: "close", group, tabId } as const
        const next = workspaceReducer(workspace, action)
        dispatch(action)
        requestAnimationFrame(() => {
            const nextId = next.groups[next.activeGroup].activeId
            const item = Array.from(document.querySelectorAll<HTMLElement>("[data-titlebar-tab]")).find(
                (element) => element.dataset.titlebarTab === nextId
            )
            item?.querySelector<HTMLInputElement>("input")?.focus()
        })
    }

    const renderAppPicker = () => (
        <Popover
            open={menuOpen}
            onOpenChange={setMenuOpen}>
            <PopoverTrigger
                className="electrobun-webkit-app-region-no-drag"

                render={
                    <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        aria-label="Open workspace menu"
                    />
                }>
                <Logo
                    aria-hidden="true"
                    focusable="false"
                    className="size-4 text-primary"
                />
                <span className="font-serif text-sm font-normal">Corpora</span>
                <ChevronDown aria-hidden="true" />
            </PopoverTrigger>
            <PopoverPopup
                align="start"
                className="electrobun-webkit-app-region-no-drag w-64">
                <PopoverTitle className="text-sm">Corpora workspace</PopoverTitle>
                <PopoverDescription className="mt-2 text-xs">
                    Documents, conversion jobs, and local tools.
                </PopoverDescription>
                <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                        resetWorkspace()
                        setMenuOpen(false)
                    }}>
                    Reset panel layout
                </Button>
            </PopoverPopup>
        </Popover>
    )

    return (
        <header className="desktop-titlebar electrobun-webkit-app-region-drag flex h-11 shrink-0 items-center justify-items-start gap-2 pr-3">
            {renderAppPicker()}
            <div className="electrobun-webkit-app-region-no-drag flex min-w-0 max-w-[70%] items-center overflow-x-auto">
                {items.length > 0 && (
                    <SegmentGroup
                        value={activeId}
                        glassOptics={theme === "light" ? {
                            frost: 0.15,
                            brightness: 0.03,
                            saturate: 1.15,
                            bend: 0.15,
                            depth: 0.35,
                            curvature: 0.3,
                            sheen: 0.5,
                            sheenWidth: 1.25,
                            glow: 0.02
                        } : undefined}
                        onValueChange={({ value }) => {
                            const destination = destinations.find((item) => item.id === value)
                            if (destination)
                                dispatch({ type: "open", target: "primary", tab: navigationTab(destination.id) })
                            else if (value) {
                                const group = workspace.groups.primary.tabs.some((tab) => tab.id === value)
                                    ? "primary"
                                    : "secondary"
                                dispatch({ type: "select", group, tabId: value })
                            }
                        }}
                        aria-label="Workspace navigation"
                        className="shrink-0">
                        {items.map((item) => (
                            <div key={item.id} className="flex shrink-0 items-center rounded-lg">
                                <SegmentGroupItem
                                    className={`px-2 py-1 text-xs font-medium flex gap-x-1 flex-row items-center ${item.pinned ? "" : "pr-7"}`}
                                    value={item.id}
                                    data-titlebar-tab={item.id}
                                    data-top-navigation={isTopNavigationTab(item) ? item.id : undefined}
                                    data-workspace-tab-id={isTopNavigationTab(item) ? undefined : item.id}
                                    onKeyDown={(event) => {
                                        if (event.key === "Delete" && !item.pinned) {
                                            event.preventDefault()
                                            close(item.id)
                                        }
                                    }}
                                    title={item.title}>
                                    {item.icon && <MorphIcon icon={item.icon} size={14} />}
                                    <SegmentGroupItemText className="block max-w-44 truncate">
                                        {item.title}
                                    </SegmentGroupItemText>
                                </SegmentGroupItem>
                                {!item.pinned && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon-xs"
                                        className="-ml-5 mr-1 z-10 size-4"
                                        aria-label={`Close ${item.title}`}
                                        onClick={() => close(item.id)}>
                                        <X aria-hidden="true" className="size-3" />
                                    </Button>
                                )}
                            </div>
                        ))}
                    </SegmentGroup>
                )}
            </div>
            <div className="min-w-8 flex-1 self-stretch" data-titlebar-drag-space aria-hidden="true" />
            <div className="electrobun-webkit-app-region-no-drag flex items-center gap-2">
                {children}
                <SettingsButton onClick={onOpenSettings} />
            </div>
        </header>
    )
}
