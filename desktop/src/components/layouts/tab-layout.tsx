import { useRef, type Dispatch, type ReactNode } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { WorkspaceAction, WorkspaceState, WorkspaceTab, TWorkspaceGroupType } from "@/lib/workspace-tabs"

interface TabLayoutProps {
    group: TWorkspaceGroupType
    workspace: WorkspaceState
    dispatch: Dispatch<WorkspaceAction>
    renderTab: (tab: WorkspaceTab) => ReactNode
}

// Selection and close controls live in the titlebar. Keep visited views mounted
// so changing the top tab does not discard a form or an editor's state.
export function TabLayout({ group, workspace, dispatch, renderTab }: TabLayoutProps) {
    const { tabs, activeId } = workspace.groups[group]
    const visited = useRef(new Set<string>())
    if (activeId) visited.current.add(activeId)

    return (
        <div
            className="h-full min-h-0 min-w-0"
            data-workspace-group={group}
            onFocusCapture={() => dispatch({ type: "focus", group })}>
            {tabs.filter((tab) => visited.current.has(tab.id)).map((tab) => (
                <section
                    key={tab.id}
                    hidden={tab.id !== activeId}
                    aria-label={`${tab.title} content`}
                    className="h-full min-h-0 min-w-0">
                    <ScrollArea scrollFade>
                        <div className="@container min-w-0 p-5">{renderTab(tab)}</div>
                    </ScrollArea>
                </section>
            ))}
        </div>
    )
}
