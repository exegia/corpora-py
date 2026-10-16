import type { ReactNode } from "react"
import { useAtom, useAtomValue, useSetAtom } from "jotai"
import { ChevronDown } from "lucide-react"
import Logo from "@/components/logo"
import { SettingsButton } from "./settings-button"
import { Button } from "./ui/shark-button"
import { Popover, PopoverDescription, PopoverPopup, PopoverTitle, PopoverTrigger } from "@/components/ui/popover"
import { SegmentGroup, SegmentGroupItem, SegmentGroupItemText } from "@/components/ui/segment-group"
import {
    activeTabAtom,
    resetWorkspaceAtom,
    workspaceAtom,
    titlebarPopoverOpenAtom,
    workspaceActionAtom
} from "@/shared/store"

import { destinations, navigationTab } from "@/shared/navigation"
import { MorphIcon } from "morphicons/react"

export interface TitleBarProps {
    onOpenSettings: () => void
    children?: ReactNode
}

export function TitleBar({ onOpenSettings, children }: TitleBarProps) {
    const [menuOpen, setMenuOpen] = useAtom(titlebarPopoverOpenAtom)
    const workspace = useAtomValue(workspaceAtom)
    // const editorTabs = Object.values(workspace.groups).flatMap((group) => group.tabs)
    const items = [...destinations.map((item) => ({ id: item.id, title: item.label, icon: item.icon }))]
    const dispatch = useSetAtom(workspaceActionAtom)
    const activeId = useAtomValue(activeTabAtom)
    const resetWorkspace = useSetAtom(resetWorkspaceAtom)

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
            <div className="electrobun-webkit-app-region-no-drag flex justify-start min-w-0 flex-1 items-center overflow-x-auto">
                {items.length > 0 && (
                    <SegmentGroup
                        value={activeId}
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
                            <SegmentGroupItem
                                className="px-2 py-1 text-xs font-medium flex gap-x-1 flex-row items-center"
                                key={item.id}
                                value={item.id}
                                data-top-navigation={item.id}
                                title={item.title}>
                                <MorphIcon
                                    icon={item.icon}
                                    size={14}
                                />
                                <SegmentGroupItemText className="block max-w-44 truncate">
                                    {item.title}
                                </SegmentGroupItemText>
                            </SegmentGroupItem>
                        ))}
                    </SegmentGroup>
                )}
            </div>
            <div className="electrobun-webkit-app-region-no-drag flex items-center gap-2">
                {children}
                <SettingsButton onClick={onOpenSettings} />
            </div>
        </header>
    )
}
