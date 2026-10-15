import { HomeTab } from "../mainview/views/home-tab"
import { ExploreTab } from "../mainview/views/explore-tab"
import { JobTab } from "../mainview/views/jobs-tab"
import { JobDetailTab } from "../mainview/views/job-detail-tab"
import { SettingsTab } from "../mainview/views/settings-tab"
import { describe, expect, test } from "bun:test"
import { activeWorkspaceTab, createWorkspaceState, jobWorkspaceTab, workspaceReducer } from "./workspace-tabs"
import type { WorkspaceAction, WorkspaceType, WorkspaceState, WorkspaceTab } from "./workspace-tabs"

const groupIds: readonly WorkspaceType[] = ["primary", "secondary"]

function jobTab(id: string): WorkspaceTab {
    return jobWorkspaceTab({ id, name: `Source ${id}`, display_name: null })
}

function withJobs(group: WorkspaceType = "primary"): WorkspaceState {
    let state = createWorkspaceState()
    for (const id of ["a", "b", "c"]) {
        state = workspaceReducer(state, { type: "open", tab: jobTab(id), target: group })
    }
    return state
}

function freezeState(state: WorkspaceState): WorkspaceState {
    for (const group of groupIds) {
        for (const tab of state.groups[group].tabs) Object.freeze(tab)
        Object.freeze(state.groups[group].tabs)
        Object.freeze(state.groups[group])
    }
    Object.freeze(state.groups)
    Object.freeze(state)
    return state
}

function expectInvariants(state: WorkspaceState): void {
    const tabs = groupIds.flatMap((group) => state.groups[group].tabs)
    expect(new Set(tabs.map((tab) => tab.id)).size).toBe(tabs.length)
    expect(state.groups.primary.tabs.find((tab) => tab.id === "tab:home")).toEqual({
        id: "tab:home",
        title: "Home",
        view: HomeTab,
        pinned: true
    })
    for (const group of groupIds) {
        const { tabs, activeId } = state.groups[group]
        if (tabs.length === 0) expect(activeId).toBeNull()
        else expect(tabs.some((tab) => tab.id === activeId)).toBe(true)
    }
    expect(groupIds).toContain(state.activeGroup)
}

describe("workspace initial state and active tab", () => {
    test("starts with a pinned primary dashboard and an unpinned secondary explorer", () => {
        const state = createWorkspaceState()
        expect(state).toEqual({
            groups: {
                primary: {
                    tabs: [{ id: "tab:home", title: "Home", view: HomeTab, pinned: true }],
                    activeId: "tab:home"
                },
                secondary: {
                    tabs: [{ id: "tab:explorer", title: "Explorer", view: ExploreTab, pinned: false }],
                    activeId: "tab:explorer"
                }
            },
            activeGroup: "primary"
        })
        expectInvariants(state)
    })

    test("creates independent states, groups, arrays and tabs", () => {
        const first = createWorkspaceState()
        const second = createWorkspaceState()
        expect(second).toEqual(first)
        expect(second).not.toBe(first)
        expect(second.groups).not.toBe(first.groups)
        for (const group of groupIds) {
            expect(second.groups[group]).not.toBe(first.groups[group])
            expect(second.groups[group].tabs).not.toBe(first.groups[group].tabs)
            expect(second.groups[group].tabs[0]).not.toBe(first.groups[group].tabs[0])
        }
    })

    test("reads the focused group by default or an explicitly requested group", () => {
        const state = createWorkspaceState()
        expect(activeWorkspaceTab(state)).toBe(state.groups.primary.tabs[0])
        expect(activeWorkspaceTab(state, "secondary")).toBe(state.groups.secondary.tabs[0])
        const focused = workspaceReducer(state, { type: "focus", group: "secondary" })
        expect(activeWorkspaceTab(focused)).toBe(state.groups.secondary.tabs[0])
    })

    test("returns null for an empty group, missing selection or invalid group", () => {
        const state = createWorkspaceState()
        const empty = workspaceReducer(state, { type: "close", group: "secondary", tabId: "tab:explorer" })
        expect(activeWorkspaceTab(empty, "secondary")).toBeNull()
        const stale: WorkspaceState = {
            ...state,
            groups: { ...state.groups, primary: { ...state.groups.primary, activeId: "missing" } }
        }
        expect(activeWorkspaceTab(stale)).toBeNull()
        expect(activeWorkspaceTab(state, "invalid" as WorkspaceType)).toBeNull()
    })
})

describe("opening workspace tabs", () => {
    test("appends, selects and focuses a new tab in an explicit target", () => {
        const state = createWorkspaceState()
        const tab = jobTab("a")
        const next = workspaceReducer(state, { type: "open", tab, target: "secondary" })
        expect(next.groups.secondary.tabs).toEqual([...state.groups.secondary.tabs, tab])
        expect(next.groups.secondary.activeId).toBe(tab.id)
        expect(next.activeGroup).toBe("secondary")
        expect(next.groups.primary).toBe(state.groups.primary)
        expect(next.groups.secondary.tabs[0]).toBe(state.groups.secondary.tabs[0])
        expect(next.groups.secondary.tabs[1]).not.toBe(tab)
        expect(state.groups.secondary.activeId).toBe("tab:explorer")
    })

    test("uses the focused group when no target is supplied", () => {
        for (const group of groupIds) {
            const state = workspaceReducer(createWorkspaceState(), { type: "focus", group })
            const next = workspaceReducer(state, { type: "open", tab: jobTab("a") })
            expect(next.groups[group].activeId).toBe("job:a")
            expect(next.activeGroup).toBe(group)
        }
    })

    test("supports jobs and settings views", () => {
        let state = createWorkspaceState()
        for (const view of ["jobs", "settings"] as const) {
            const tab: WorkspaceTab = {
                id: view,
                title: view,
                view: view === "jobs" ? JobTab : SettingsTab,
                pinned: false
            }
            state = workspaceReducer(state, { type: "open", tab })
            expect(activeWorkspaceTab(state)).toEqual(tab)
        }
    })

    test("deduplicates within a group without overwriting existing tab metadata", () => {
        const state = withJobs()
        const next = workspaceReducer(state, {
            type: "open",
            tab: { ...jobTab("a"), title: "Changed title", pinned: true }
        })
        expect(next.groups.primary.tabs).toBe(state.groups.primary.tabs)
        expect(next.groups.primary.activeId).toBe("job:a")
        expect(activeWorkspaceTab(next)).toEqual(jobTab("a"))
        expect(next.groups.secondary).toBe(state.groups.secondary)
        expectInvariants(next)
    })

    test("deduplicates globally and focuses the existing group instead of the requested target", () => {
        for (const existingGroup of groupIds) {
            const target = existingGroup === "primary" ? "secondary" : "primary"
            const state = workspaceReducer(withJobs(existingGroup), { type: "focus", group: target })
            const next = workspaceReducer(state, { type: "open", tab: jobTab("a"), target })
            expect(next.activeGroup).toBe(existingGroup)
            expect(next.groups[existingGroup].activeId).toBe("job:a")
            expect(next.groups[existingGroup].tabs).toBe(state.groups[existingGroup].tabs)
            expect(next.groups[target]).toBe(state.groups[target])
            expectInvariants(next)
        }
    })

    test("reopening the dashboard in secondary leaves the dashboard in primary", () => {
        const state = workspaceReducer(createWorkspaceState(), { type: "focus", group: "secondary" })
        const next = workspaceReducer(state, {
            type: "open",
            tab: { id: "tab:home", title: "Replacement", view: SettingsTab, pinned: false },
            target: "secondary"
        })
        expect(next.activeGroup).toBe("primary")
        expect(next.groups).toBe(state.groups)
        expectInvariants(next)
    })

    test("reopening an already focused tab is a reference-preserving no-op", () => {
        const state = withJobs()
        expect(workspaceReducer(state, { type: "open", tab: jobTab("c") })).toBe(state)
    })

    test("equal titles do not deduplicate different IDs", () => {
        let state = createWorkspaceState()
        for (const id of ["a", "b"]) {
            state = workspaceReducer(state, { type: "open", tab: { ...jobTab(id), title: "Same title" } })
        }
        expect(state.groups.primary.tabs.map((tab) => tab.id)).toEqual(["tab:home", "job:a", "job:b"])
        expectInvariants(state)
    })
})

describe("selecting and focusing workspace groups", () => {
    test("selection updates only the chosen group and focuses it", () => {
        const state = workspaceReducer(withJobs("secondary"), { type: "focus", group: "primary" })
        const next = workspaceReducer(state, { type: "select", group: "secondary", tabId: "job:a" })
        expect(next.activeGroup).toBe("secondary")
        expect(next.groups.secondary.activeId).toBe("job:a")
        expect(next.groups.secondary.tabs).toBe(state.groups.secondary.tabs)
        expect(next.groups.primary).toBe(state.groups.primary)
        expect(state.groups.secondary.activeId).toBe("job:c")
    })

    test("selecting the selected tab in another group only changes focus", () => {
        const state = createWorkspaceState()
        const next = workspaceReducer(state, { type: "select", group: "secondary", tabId: "tab:explorer" })
        expect(next.activeGroup).toBe("secondary")
        expect(next.groups).toBe(state.groups)
        expect(workspaceReducer(next, { type: "select", group: "secondary", tabId: "tab:explorer" })).toBe(next)
    })

    test("focus preserves both selections and all group references", () => {
        const state = withJobs()
        const next = workspaceReducer(state, { type: "focus", group: "secondary" })
        expect(next.groups).toBe(state.groups)
        expect(next.activeGroup).toBe("secondary")
        expect(workspaceReducer(next, { type: "focus", group: "secondary" })).toBe(next)
    })

    test("an empty secondary group can be focused without selecting a nonexistent tab", () => {
        const empty = workspaceReducer(createWorkspaceState(), {
            type: "close",
            group: "secondary",
            tabId: "tab:explorer"
        })
        const next = workspaceReducer(empty, { type: "focus", group: "secondary" })
        expect(next.activeGroup).toBe("secondary")
        expect(activeWorkspaceTab(next)).toBeNull()
        expect(next.groups).toBe(empty.groups)
    })
})

describe("closing workspace tabs", () => {
    test("closing the active tab chooses its right neighbor before its left neighbor", () => {
        for (const group of groupIds) {
            const state = workspaceReducer(withJobs(group), { type: "select", group, tabId: "job:b" })
            const next = workspaceReducer(state, { type: "close", group, tabId: "job:b" })
            expect(next.groups[group].activeId).toBe("job:c")
            expect(next.groups[group].tabs.some((tab) => tab.id === "job:b")).toBe(false)
            expectInvariants(next)
        }
    })

    test("closing the last active tab chooses the left neighbor", () => {
        for (const group of groupIds) {
            const next = workspaceReducer(withJobs(group), { type: "close", group, tabId: "job:c" })
            expect(next.groups[group].activeId).toBe("job:b")
        }
    })

    test("closing the first secondary tab chooses the right neighbor", () => {
        const state = workspaceReducer(withJobs("secondary"), {
            type: "select",
            group: "secondary",
            tabId: "tab:explorer"
        })
        const next = workspaceReducer(state, { type: "close", group: "secondary", tabId: "tab:explorer" })
        expect(next.groups.secondary.activeId).toBe("job:a")
    })

    test("closing an inactive tab preserves selection, group focus and the other group", () => {
        const state = workspaceReducer(withJobs(), { type: "focus", group: "secondary" })
        const next = workspaceReducer(state, { type: "close", group: "primary", tabId: "job:a" })
        expect(next.groups.primary.activeId).toBe("job:c")
        expect(next.activeGroup).toBe("secondary")
        expect(next.groups.secondary).toBe(state.groups.secondary)
        expect(next.groups.primary.tabs).not.toBe(state.groups.primary.tabs)
        expect(next.groups.primary.tabs[0]).toBe(state.groups.primary.tabs[0])
        expect(state.groups.primary.tabs).toHaveLength(4)
    })

    test("closing the only secondary tab leaves an empty group without stealing focus", () => {
        const state = workspaceReducer(createWorkspaceState(), { type: "focus", group: "secondary" })
        const next = workspaceReducer(state, { type: "close", group: "secondary", tabId: "tab:explorer" })
        expect(next.groups.secondary).toEqual({ tabs: [], activeId: null })
        expect(next.activeGroup).toBe("secondary")
        expect(next.groups.primary).toBe(state.groups.primary)
        expectInvariants(next)
        const reopened = workspaceReducer(next, { type: "open", tab: jobTab("a") })
        expect(reopened.groups.secondary).toEqual({ tabs: [jobTab("a")], activeId: "job:a" })
    })

    test("the dashboard and other pinned tabs cannot close", () => {
        const state = createWorkspaceState()
        expect(workspaceReducer(state, { type: "close", group: "primary", tabId: "tab:home" })).toBe(state)
        const pinned = workspaceReducer(state, { type: "open", tab: { ...jobTab("a"), pinned: true } })
        expect(workspaceReducer(pinned, { type: "close", group: "primary", tabId: "job:a" })).toBe(pinned)
    })
})

describe("moving workspace tabs", () => {
    test("moves an active tab in either direction and selects and focuses its destination", () => {
        for (const group of groupIds) {
            const target = group === "primary" ? "secondary" : "primary"
            const state = workspaceReducer(withJobs(group), { type: "select", group, tabId: "job:b" })
            const tab = activeWorkspaceTab(state)
            if (!tab) throw new Error("Expected the selected job tab before moving it")
            const next = workspaceReducer(state, { type: "move", group, tabId: "job:b", target })
            expect(next.groups[group].activeId).toBe("job:c")
            expect(next.groups[group].tabs.some((tab) => tab.id === "job:b")).toBe(false)
            expect(next.groups[target].tabs).toEqual([...state.groups[target].tabs, tab])
            expect(next.groups[target].activeId).toBe("job:b")
            expect(activeWorkspaceTab(next)).toBe(tab)
            expect(next.activeGroup).toBe(target)
            expect(next.groups[group]).not.toBe(state.groups[group])
            expect(next.groups[target]).not.toBe(state.groups[target])
            expect(state.groups[group].tabs).toHaveLength(4)
            expect(state.groups[target].tabs).toHaveLength(1)
            expectInvariants(next)
        }
    })

    test("moving the last active tab falls back to its left neighbor", () => {
        const next = workspaceReducer(withJobs(), {
            type: "move",
            group: "primary",
            tabId: "job:c",
            target: "secondary"
        })
        expect(next.groups.primary.activeId).toBe("job:b")
    })

    test("moving an inactive tab preserves the source selection", () => {
        const state = withJobs()
        const next = workspaceReducer(state, { type: "move", group: "primary", tabId: "job:a", target: "secondary" })
        expect(next.groups.primary.activeId).toBe("job:c")
        expect(next.groups.secondary.activeId).toBe("job:a")
        expect(next.activeGroup).toBe("secondary")
    })

    test("moving the sole secondary tab empties the source", () => {
        const next = workspaceReducer(createWorkspaceState(), {
            type: "move",
            group: "secondary",
            tabId: "tab:explorer",
            target: "primary"
        })
        expect(next.groups.secondary).toEqual({ tabs: [], activeId: null })
        expect(next.groups.primary.tabs.map((tab) => tab.id)).toEqual(["tab:home", "tab:explorer"])
        expect(next.groups.primary.activeId).toBe("tab:explorer")
        expectInvariants(next)
    })

    test("moving to an empty secondary group selects the moved tab", () => {
        const empty = workspaceReducer(withJobs(), { type: "close", group: "secondary", tabId: "tab:explorer" })
        const next = workspaceReducer(empty, { type: "move", group: "primary", tabId: "job:a", target: "secondary" })
        expect(next.groups.secondary).toEqual({ tabs: [jobTab("a")], activeId: "job:a" })
        expectInvariants(next)
    })

    test("the dashboard and other pinned tabs cannot move", () => {
        const state = createWorkspaceState()
        expect(
            workspaceReducer(state, { type: "move", group: "primary", tabId: "tab:home", target: "secondary" })
        ).toBe(state)
        const pinned = workspaceReducer(state, { type: "open", tab: { ...jobTab("a"), pinned: true } })
        expect(workspaceReducer(pinned, { type: "move", group: "primary", tabId: "job:a", target: "secondary" })).toBe(
            pinned
        )
    })

    test("moving within the same group does not reorder or focus it", () => {
        const state = workspaceReducer(withJobs(), { type: "focus", group: "secondary" })
        expect(workspaceReducer(state, { type: "move", group: "primary", tabId: "job:a", target: "primary" })).toBe(
            state
        )
    })

    test("refuses a move that would duplicate an ID already present in the target", () => {
        const state = withJobs()
        const duplicated: WorkspaceState = {
            ...state,
            groups: {
                ...state.groups,
                secondary: { tabs: [...state.groups.secondary.tabs, jobTab("a")], activeId: "tab:explorer" }
            }
        }
        expect(
            workspaceReducer(duplicated, { type: "move", group: "primary", tabId: "job:a", target: "secondary" })
        ).toBe(duplicated)
    })
})

describe("invalid actions and immutable updates", () => {
    test("missing, malformed, unknown and incorrectly scoped actions are reference-preserving no-ops", () => {
        const state = freezeState(withJobs())
        expect(workspaceReducer(state)).toBe(state)
        const invalidActions: unknown[] = [
            undefined,
            null,
            false,
            1,
            "open",
            {},
            [],
            { type: "unknown" },
            { type: "open" },
            { type: "open", tab: null },
            { type: "open", tab: jobTab("d"), target: "invalid" },
            { type: "open", tab: jobTab("a"), target: null },
            { type: "select" },
            { type: "close" },
            { type: "move" },
            { type: "focus" },
            { type: "select", group: "primary", tabId: "missing" },
            { type: "select", group: "primary", tabId: "tab:explorer" },
            { type: "close", group: "secondary", tabId: "job:a" },
            { type: "move", group: "primary", tabId: "missing", target: "secondary" },
            { type: "move", group: "primary", tabId: "job:a" },
            { type: "move", group: "primary", tabId: "job:a", target: "invalid" }
        ]
        for (const group of ["invalid", "toString", "__proto__", null]) {
            for (const type of ["select", "close", "move", "focus"]) {
                invalidActions.push({ type, group, tabId: "job:a", target: "secondary" })
            }
        }
        for (const action of invalidActions) {
            expect(workspaceReducer(state, action as WorkspaceAction)).toBe(state)
        }
    })

    test("rejects malformed tab fields without altering state", () => {
        const state = createWorkspaceState()
        const tab = jobTab("a")
        const invalidTabs: unknown[] = [
            {},
            [],
            { ...tab, id: "" },
            { ...tab, id: "  " },
            { ...tab, id: 1 },
            { ...tab, title: null },
            { ...tab, view: "unknown" },
            { ...tab, pinned: "false" },
            { ...tab, jobId: 1 },
            { id: "jobs", title: "Jobs", view: JobTab }
        ]
        for (const invalidTab of invalidTabs) {
            expect(workspaceReducer(state, { type: "open", tab: invalidTab as WorkspaceTab })).toBe(state)
        }
    })

    test("dashboard protection does not depend only on its pinned flag", () => {
        const state = createWorkspaceState()
        const unpinned: WorkspaceState = {
            ...state,
            groups: {
                ...state.groups,
                primary: { tabs: [{ ...state.groups.primary.tabs[0], pinned: false }], activeId: "tab:home" }
            }
        }
        expect(workspaceReducer(unpinned, { type: "close", group: "primary", tabId: "tab:home" })).toBe(unpinned)
        expect(
            workspaceReducer(unpinned, { type: "move", group: "primary", tabId: "tab:home", target: "secondary" })
        ).toBe(unpinned)
    })

    test("all transitions accept frozen inputs and preserve invariants without mutating state or actions", () => {
        const actions: WorkspaceAction[] = [
            { type: "open", tab: jobTab("a") },
            { type: "open", tab: jobTab("b") },
            { type: "open", tab: jobTab("a"), target: "secondary" },
            { type: "select", group: "primary", tabId: "tab:home" },
            { type: "move", group: "primary", tabId: "job:a", target: "secondary" },
            { type: "focus", group: "primary" },
            { type: "close", group: "secondary", tabId: "tab:explorer" },
            { type: "close", group: "primary", tabId: "job:b" },
            { type: "close", group: "secondary", tabId: "job:a" },
            { type: "open", tab: jobTab("c"), target: "secondary" },
            { type: "move", group: "secondary", tabId: "job:c", target: "primary" },
            { type: "close", group: "primary", tabId: "tab:home" }
        ]
        let state = createWorkspaceState()
        for (const action of actions) {
            freezeState(state)
            if (action.type === "open") Object.freeze(action.tab)
            Object.freeze(action)
            const before = {
                ...state,
                groups: {
                    primary: { ...state.groups.primary, tabs: state.groups.primary.tabs.map((tab) => ({ ...tab })) },
                    secondary: {
                        ...state.groups.secondary,
                        tabs: state.groups.secondary.tabs.map((tab) => ({ ...tab }))
                    }
                }
            }
            const originalAction = action.type === "open" ? { ...action, tab: { ...action.tab } } : { ...action }
            const next = workspaceReducer(state, action)
            expect(state).toEqual(before)
            expect(action).toEqual(originalAction)
            expectInvariants(next)
            state = next
        }
    })
})

describe("job workspace tabs", () => {
    test("uses a stable namespaced ID, job view, original job ID and display name", () => {
        const job = Object.freeze({ id: "123", name: "source.epub", display_name: "A readable title" })
        expect(jobWorkspaceTab(job)).toEqual({
            id: "job:123",
            title: "A readable title",
            view: JobDetailTab,
            pinned: false,
            jobId: "123"
        })
        expect(job).toEqual({ id: "123", name: "source.epub", display_name: "A readable title" })
    })

    test("falls back to the source name for a null or empty display name", () => {
        for (const display_name of [null, ""]) {
            expect(jobWorkspaceTab({ id: "a", name: "source.epub", display_name }).title).toBe("source.epub")
        }
    })

    test("keeps provided display names unchanged and creates fresh tab objects", () => {
        const job = { id: "a:b", name: "source.epub", display_name: "  Ελληνικά 📖  " }
        const first = jobWorkspaceTab(job)
        const second = jobWorkspaceTab(job)
        expect(first.title).toBe(job.display_name)
        expect(first.id).toBe("job:a:b")
        expect(second).toEqual(first)
        expect(second).not.toBe(first)
    })

    test("changed job names do not change identity or create duplicate tabs", () => {
        const state = workspaceReducer(createWorkspaceState(), { type: "open", tab: jobTab("a"), target: "secondary" })
        const renamed = jobWorkspaceTab({ id: "a", name: "renamed.epub", display_name: "New title" })
        const next = workspaceReducer(state, { type: "open", tab: renamed, target: "primary" })
        expect(next).toBe(state)
        expect(activeWorkspaceTab(next)?.title).toBe("Source a")
        expectInvariants(next)
    })
})
