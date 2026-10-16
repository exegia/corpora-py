import { HomeTab } from "@/mainview/views/home-tab"
import type { ComponentType } from "react"
import { JobDetailTab } from "@/mainview/views/job-detail-tab"
import type { ConversionJob } from "@/shared/conversion"
import type { WorkspaceViewProps } from "./workspace-view"

export type WorkspaceType = "primary" | "secondary" | "primary-dock" | "secondary-dock"

export interface WorkspaceTab {
    readonly id: string
    title: string
    view: ComponentType<WorkspaceViewProps>
    pinned: boolean
    jobId?: string
}

export function isTopNavigationTab(tab: Pick<WorkspaceTab, "id">): boolean {
    return tab.id === "tab:home" || tab.id === "tab:explorer"
}

export function isJobWorkspaceTab(tab: WorkspaceTab): boolean {
    return tab.view === JobDetailTab || typeof tab.jobId === "string" || tab.id.startsWith("job:")
}

export function jobWorkspaceTab(job: Pick<ConversionJob, "id" | "name" | "display_name">): WorkspaceTab {
    return {
        id: `job:${job.id}`,
        title: job.display_name || job.name,
        view: JobDetailTab,
        pinned: false,
        jobId: job.id
    }
}

export interface WorkspaceTabGroup {
    tabs: WorkspaceTab[]
    activeId: string | null
}

export type TWorkspaceGroupType = Exclude<WorkspaceType, "primary-dock" | "secondary-dock">
export interface WorkspaceState<W extends TWorkspaceGroupType = TWorkspaceGroupType> {
    groups: Record<W, WorkspaceTabGroup>
    activeGroup: W
}

export type WorkspaceAction =
    | { type: "open"; tab: WorkspaceTab; target?: TWorkspaceGroupType }
    | { type: "select"; group: TWorkspaceGroupType; tabId: WorkspaceTab["id"] }
    | { type: "close"; group: TWorkspaceGroupType; tabId: WorkspaceTab["id"] }
    | { type: "move"; group: TWorkspaceGroupType; tabId: WorkspaceTab["id"]; target: TWorkspaceGroupType }
    | { type: "focus"; group: TWorkspaceGroupType }

const groupIds: readonly TWorkspaceGroupType[] = ["primary", "secondary"]

function isGroupId(value: unknown): value is TWorkspaceGroupType {
    return value === "primary" || value === "secondary"
}

function isWorkspaceTab(value: unknown): value is WorkspaceTab {
    if (typeof value !== "object" || value === null) return false
    return (
        "id" in value &&
        typeof value.id === "string" &&
        value.id.trim().length > 0 &&
        "title" in value &&
        typeof value.title === "string" &&
        "view" in value &&
        typeof value.view === "function" &&
        "pinned" in value &&
        typeof value.pinned === "boolean" &&
        (!("jobId" in value) || value.jobId === undefined || typeof value.jobId === "string")
    )
}

export function createWorkspaceState(): WorkspaceState {
    return {
        groups: {
            primary: {
                tabs: [{ id: "tab:home", title: "Home", view: HomeTab, pinned: true }],
                activeId: "tab:home"
            },
            secondary: {
                tabs: [],
                activeId: null
            }
        },
        activeGroup: "primary"
    }
}

export function activeWorkspaceTab(
    state: WorkspaceState,
    group: WorkspaceType = state.activeGroup
): WorkspaceTab | null {
    if (!isGroupId(group)) return null
    const { tabs, activeId } = state.groups[group]
    return tabs.find((tab) => tab.id === activeId) ?? null
}

function selectTab(state: WorkspaceState, group: TWorkspaceGroupType, tabId: string): WorkspaceState {
    const selected = state.groups[group]
    if (selected.activeId === tabId) {
        return state.activeGroup === group ? state : { ...state, activeGroup: group }
    }
    return {
        ...state,
        groups: { ...state.groups, [group]: { ...selected, activeId: tabId } },
        activeGroup: group
    }
}

function removeTab(group: WorkspaceTabGroup, index: number): WorkspaceTabGroup {
    const tab = group.tabs[index]
    return {
        tabs: group.tabs.filter((_, tabIndex) => tabIndex !== index),
        activeId:
            group.activeId === tab?.id
                ? (group.tabs[index + 1]?.id ?? group.tabs[index - 1]?.id ?? null)
                : group.activeId
    }
}

export function workspaceReducer(state: WorkspaceState, action?: WorkspaceAction | null): WorkspaceState {
    if (typeof action !== "object" || action === null) return state

    switch (action.type) {
        case "open": {
            const target = isTopNavigationTab(action.tab ?? { id: "" })
                ? "primary"
                : action.target === undefined
                  ? state.activeGroup
                  : action.target
            if (!isGroupId(target) || !isWorkspaceTab(action.tab)) return state
            for (const group of groupIds) {
                if (state.groups[group].tabs.some((tab) => tab.id === action.tab.id)) {
                    return selectTab(state, group, action.tab.id)
                }
            }
            const group = state.groups[target]
            return {
                ...state,
                groups: {
                    ...state.groups,
                    [target]: { tabs: [...group.tabs, { ...action.tab }], activeId: action.tab.id }
                },
                activeGroup: target
            }
        }
        case "select": {
            if (!isGroupId(action.group)) return state
            if (!state.groups[action.group].tabs.some((tab) => tab.id === action.tabId)) return state
            return selectTab(state, action.group, action.tabId)
        }
        case "close": {
            if (!isGroupId(action.group)) return state
            const group = state.groups[action.group]
            const index = group.tabs.findIndex((tab) => tab.id === action.tabId)
            const tab = group.tabs[index]
            if (!tab || tab.pinned || isTopNavigationTab(tab)) return state
            return {
                ...state,
                groups: { ...state.groups, [action.group]: removeTab(group, index) },
                activeGroup: action.group === "secondary" && group.tabs.length === 1 ? "primary" : state.activeGroup
            }
        }
        case "move": {
            if (!isGroupId(action.group) || !isGroupId(action.target) || action.group === action.target) return state
            const source = state.groups[action.group]
            const target = state.groups[action.target]
            const index = source.tabs.findIndex((tab) => tab.id === action.tabId)
            const tab = source.tabs[index]
            if (!tab || tab.pinned || isTopNavigationTab(tab)) return state
            if (target.tabs.some((existing) => existing.id === tab.id)) return state
            return {
                ...state,
                groups: {
                    ...state.groups,
                    [action.group]: removeTab(source, index),
                    [action.target]: { tabs: [...target.tabs, tab], activeId: tab.id }
                },
                activeGroup: action.target
            }
        }
        case "focus": {
            if (!isGroupId(action.group) || state.activeGroup === action.group) return state
            return { ...state, activeGroup: action.group }
        }
        default:
            return state
    }
}
