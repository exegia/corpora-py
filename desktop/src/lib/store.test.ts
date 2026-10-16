import "../mainview/panel-plugins"
import { defaultPluginPlacements } from "./panel"
import { HomeTab } from "../mainview/views/home-tab"
import { ExploreTab } from "../mainview/views/explore-tab"
import { JobTab } from "../mainview/views/jobs-tab"
import { JobDetailTab } from "../mainview/views/job-detail-tab"
import { SettingsTab } from "../mainview/views/settings-tab"
import { describe, expect, spyOn, test } from "bun:test"
import { createStore } from "jotai"
import { createElement } from "react"
import { BookSearch, House, type LucideIcon } from "lucide-react"
import { destinations as navigation, navigationTab, type TabID } from "../shared/navigation"
import * as atoms from "../shared/store"
import type { ConversionJob } from "../shared/conversion"
import type { ConversionDraft } from "../shared/store-types"
import type { SidecarStatus } from "../shared/rpc"
import type { FileUploadState } from "../hooks/use-file-upload"
import { BackendPolling } from "./backend-polling"
import { ConversionClient, type ConversionSnapshot } from "./conversion-client"
import { createWorkspaceState, jobWorkspaceTab, type WorkspaceAction, type WorkspaceTab } from "./workspace-tabs"

type TestStore = ReturnType<typeof createStore>

const starting: SidecarStatus = { state: "starting", url: null, error: null, authRequired: null }
const ready: SidecarStatus = { state: "ready", url: "http://127.0.0.1:8001", error: null, authRequired: false }
const defaultLevels = ["debug", "info", "warning", "error", "unclassified"]

function job(id: string): ConversionJob {
    return {
        id,
        name: `Source ${id}`,
        display_name: null,
        source_format: "plain",
        output_format: "corpus",
        status: "queued",
        created_at: 1000,
        started_at: null,
        finished_at: null,
        error: null,
        logs: [],
        last_log: null,
        events: [],
        steps: [],
        validation: null,
        result_filename: `${id}.corpus`,
        download_ready: false
    }
}

function snapshot(jobs: ConversionJob[] = []): ConversionSnapshot {
    return { jobs, isLoading: false, isSubmitting: false, error: null }
}

function publishJobs(store: TestStore, jobs: ConversionJob[]): ConversionSnapshot {
    const value = snapshot(jobs)
    store.set(atoms.conversionSnapshotSourceAtom, { client: store.get(atoms.conversionClientAtom), snapshot: value })
    return value
}

function setBackend(store: TestStore, backend: SidecarStatus): void {
    store.set(atoms.backendSnapshotAtom, (previous) => ({ ...previous, backend }))
}

function draft(): ConversionDraft {
    return {
        name: "Retained corpus",
        description: "Source notes",
        source_format: "plain",
        output_format: "cusx",
        category: "book"
    }
}

function upload(previews: (string | undefined)[] = [undefined]): FileUploadState {
    return {
        files: previews.map((preview, index) => ({
            id: `file-${index}`,
            file: new File(["Source text"], `source-${index}.txt`, { type: "text/plain" }),
            preview
        })),
        isDragging: true,
        errors: ["Previous upload error"]
    }
}

function panelState(store: TestStore) {
    return {
        leftWidth: store.get(atoms.sidebarWidthAtom),
        rightWidth: store.get(atoms.inspectorWidthAtom),
        secondaryWidth: store.get(atoms.secondaryWidthAtom),
        bottomHeight: store.get(atoms.dockHeightAtom),
        leftCollapsed: store.get(atoms.sidebarCollapsedAtom),
        rightCollapsed: store.get(atoms.inspectorCollapsedAtom),
        secondaryCollapsed: store.get(atoms.secondaryCollapsedAtom),
        dockCollapsed: store.get(atoms.dockCollapsedAtom),
        plugins: store.get(atoms.pluginPlacementsAtom),
        titlebarPopoverOpen: store.get(atoms.titlebarPopoverOpenAtom)
    }
}

function changePanels(store: TestStore): void {
    store.set(atoms.sidebarWidthAtom, 310)
    store.set(atoms.inspectorWidthAtom, 420)
    store.set(atoms.secondaryWidthAtom, "60%")
    store.set(atoms.dockHeightAtom, 330)
    store.set(atoms.sidebarCollapsedAtom, true)
    store.set(atoms.inspectorCollapsedAtom, true)
    store.set(atoms.secondaryCollapsedAtom, true)
    store.set(atoms.dockCollapsedAtom, true)
    store.set(atoms.panelActionAtom, { type: "open", id: "dock-logs" })
    store.set(atoms.dockCollapsedAtom, true)
    store.set(atoms.titlebarPopoverOpenAtom, true)
}

function expectWorkspaceDerived(store: TestStore): void {
    const workspace = store.get(atoms.workspaceAtom)
    const group = workspace.groups[workspace.activeGroup]
    expect(store.get(atoms.tabItemsAtom)).toBe(group.tabs)
    expect(store.get(atoms.activeTabAtom)).toBe(group.activeId)
    expect(store.get(atoms.activeWorkspaceTabAtom)).toBe(group.tabs.find((tab) => tab.id === group.activeId) ?? null)
    const tabs = Object.values(workspace.groups).flatMap((entry) => entry.tabs)
    expect(new Set(tabs.map((tab) => tab.id)).size).toBe(tabs.length)
    expect(workspace.groups.primary.tabs[0]).toEqual({
        id: "tab:home",
        title: "Home",
        view: HomeTab,
        pinned: true
    })
    for (const entry of Object.values(workspace.groups)) {
        if (entry.tabs.length === 0) expect(entry.activeId).toBeNull()
        else expect(entry.tabs.some((tab) => tab.id === entry.activeId)).toBe(true)
    }
}

function seedConversionViews(store: TestStore): void {
    store.set(atoms.jobsCreatingAtom, false)
    store.set(atoms.jobsSelectedIdAtom, "a")
    store.set(atoms.jobsQueryAtom, "source")
    store.set(atoms.jobsStatusFilterAtom, "running")
    store.set(atoms.jobsRefreshingAtom, true)
    store.set(atoms.jobsLocalErrorAtom, "Refresh failed")
    store.set(atoms.jobsAnnouncementAtom, "Job selected")
    store.set(atoms.inspectedJobIdAtom, "a")
    store.set(atoms.conversionDraftAtom, draft())
    store.set(atoms.fileUploadAtom, upload())
    store.set(atoms.conversionStepAtom, 2)
    store.set(atoms.conversionFormErrorAtom, "Review failed")
    store.set(atoms.conversionPendingAtom, true)
    const detail = atoms.conversionDetailAtomsFor("0:a")
    store.set(detail.stage, "parse")
    store.set(detail.downloading, true)
    store.set(detail.downloadError, "Download failed")
    for (const scope of ["detail", "dock"]) {
        const logs = atoms.conversionLogAtomsFor(`0:${scope}:a`)
        store.set(logs.search, scope)
        store.set(logs.selectedLevels, ["error"])
        store.set(logs.copyState, "copied")
        store.set(logs.copyError, "Clipboard failed")
        store.set(logs.copiedText, "Previous logs")
    }
}

function expectFormReset(store: TestStore): void {
    expect(store.get(atoms.conversionDraftAtom)).toEqual(atoms.initialConversionDraft)
    expect(store.get(atoms.fileUploadAtom)).toEqual({ files: [], isDragging: false, errors: [] })
    expect(store.get(atoms.conversionStepAtom)).toBe(0)
    expect(store.get(atoms.conversionFormErrorAtom)).toBeNull()
    expect(store.get(atoms.conversionPendingAtom)).toBe(false)
}

function expectConversionViewsReset(store: TestStore): void {
    expect(store.get(atoms.jobsCreatingAtom)).toBeNull()
    expect(store.get(atoms.jobsSelectedIdAtom)).toBeNull()
    expect(store.get(atoms.jobsQueryAtom)).toBe("")
    expect(store.get(atoms.jobsStatusFilterAtom)).toBe("all")
    expect(store.get(atoms.jobsRefreshingAtom)).toBe(false)
    expect(store.get(atoms.jobsLocalErrorAtom)).toBeNull()
    expect(store.get(atoms.jobsAnnouncementAtom)).toBe("")
    expect(store.get(atoms.inspectedJobIdAtom)).toBeNull()
    const detail = atoms.conversionDetailAtomsFor("0:a")
    expect(store.get(detail.stage)).toBeNull()
    expect(store.get(detail.downloading)).toBe(false)
    expect(store.get(detail.downloadError)).toBeNull()
    for (const scope of ["detail", "dock"]) {
        const logs = atoms.conversionLogAtomsFor(`0:${scope}:a`)
        expect(store.get(logs.search)).toBe("")
        expect(store.get(logs.selectedLevels)).toEqual(defaultLevels)
        expect(store.get(logs.copyState)).toBe("idle")
        expect(store.get(logs.copyError)).toBeNull()
        expect(store.get(logs.copiedText)).toBeNull()
    }
    expectFormReset(store)
}

function revocationSpy() {
    return spyOn(URL, "revokeObjectURL").mockImplementation(() => {})
}

function withRevocationSpy(run: (revoke: ReturnType<typeof revocationSpy>) => void): void {
    const revoke = revocationSpy()
    try {
        run(revoke)
    } finally {
        revoke.mockRestore()
    }
}

describe("store workspace and shared tab derivations", () => {
    test("starts on unsplit Home with a fixed sidebar and collapsed inspector", () => {
        const store = createStore()
        expect(store.get(atoms.workspaceAtom)).toEqual(createWorkspaceState())
        expect(store.get(atoms.activeTabAtom)).toBe("tab:home")
        expect(store.get(atoms.activeWorkspaceTabAtom)?.view).toBe(HomeTab)
        expect(panelState(store)).toEqual({
            leftWidth: atoms.PANEL_DEFAULT_WIDTH,
            rightWidth: atoms.PANEL_DEFAULT_WIDTH,
            secondaryWidth: "45%",
            bottomHeight: 210,
            leftCollapsed: false,
            rightCollapsed: true,
            secondaryCollapsed: true,
            dockCollapsed: true,
            plugins: defaultPluginPlacements(),
            titlebarPopoverOpen: false
        })
        expectWorkspaceDerived(store)
    })

    test("reopening the selected secondary tab reveals its editor even when selection is unchanged", () => {
        const store = createStore()
        const tab = jobWorkspaceTab(job("a"))
        store.set(atoms.workspaceActionAtom, { type: "open", tab, target: "secondary" })
        const previous = store.get(atoms.workspaceAtom)
        store.set(atoms.secondaryCollapsedAtom, true)
        store.set(atoms.workspaceActionAtom, { type: "open", tab })
        expect(store.get(atoms.workspaceAtom)).toBe(previous)
        expect(store.get(atoms.secondaryCollapsedAtom)).toBe(false)
    })

    test("open, focus and activeTab writes share the same workspace selection", () => {
        const store = createStore()
        for (const id of ["a", "b"])
            store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job(id)), target: "secondary" })
        store.set(atoms.activeTabAtom, "job:a")
        expect(store.get(atoms.activeWorkspaceTabAtom)?.jobId).toBe("a")
        expectWorkspaceDerived(store)
        store.set(atoms.workspaceActionAtom, { type: "focus", group: "primary" })
        expect(store.get(atoms.activeTabAtom)).toBe("tab:home")
        store.set(atoms.workspaceActionAtom, { type: "focus", group: "secondary" })
        expect(store.get(atoms.activeTabAtom)).toBe("job:a")
        const before = store.get(atoms.workspaceAtom)
        store.set(atoms.activeTabAtom, "tab:home")
        expect(store.get(atoms.workspaceAtom)).toBe(before)
        expectWorkspaceDerived(store)
    })

    test("reopening a job in another group focuses its existing tab without duplicates", () => {
        const store = createStore()
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("a")) })
        const existing = store.get(atoms.activeWorkspaceTabAtom)
        store.set(atoms.workspaceActionAtom, { type: "focus", group: "secondary" })
        store.set(atoms.workspaceActionAtom, {
            type: "open",
            tab: jobWorkspaceTab({ ...job("a"), display_name: "Renamed" }),
            target: "secondary"
        })
        expect(store.get(atoms.workspaceAtom).activeGroup).toBe("primary")
        expect(store.get(atoms.activeWorkspaceTabAtom)).toBe(existing)
        expectWorkspaceDerived(store)
    })

    test.each(["close", "move"] as const)("%s protects the dashboard and other pinned tabs", (type) => {
        const store = createStore()
        store.set(atoms.workspaceActionAtom, {
            type: "open",
            tab: { id: "settings", title: "Settings", view: SettingsTab, pinned: true }
        })
        const before = store.get(atoms.workspaceAtom)
        for (const tabId of ["tab:home", "settings"]) {
            if (type === "close") store.set(atoms.workspaceActionAtom, { type, group: "primary", tabId })
            else store.set(atoms.workspaceActionAtom, { type, group: "primary", tabId, target: "secondary" })
            expect(store.get(atoms.workspaceAtom)).toBe(before)
            expectWorkspaceDerived(store)
        }
    })

    test("closing active tabs selects the right neighbor, then the left, then null in an empty group", () => {
        const store = createStore()
        for (const id of ["a", "b", "c"]) {
            store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job(id)), target: "secondary" })
        }
        store.set(atoms.activeTabAtom, "job:b")
        for (const [tabId, nextId] of [
            ["job:b", "job:c"],
            ["job:c", "job:a"],
            ["job:a", null]
        ]) {
            store.set(atoms.workspaceActionAtom, { type: "close", group: "secondary", tabId: tabId! })
            expect(store.get(atoms.workspaceAtom).groups.secondary.activeId).toBe(nextId)
            expectWorkspaceDerived(store)
        }
        expect(store.get(atoms.workspaceAtom).groups.secondary.tabs).toEqual([])
        expect(store.get(atoms.activeTabAtom)).toBe("tab:home")
        expect(store.get(atoms.secondaryCollapsedAtom)).toBe(true)
    })

    test("moving a job updates both selections and retains the moved tab and job state", () => {
        const store = createStore()
        const detail = atoms.conversionDetailAtomsFor("0:a")
        const logs = atoms.conversionLogAtomsFor("0:detail:a")
        store.set(detail.stage, "parse")
        store.set(logs.search, "retained")
        for (const id of ["a", "b", "c"])
            store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job(id)) })
        store.set(atoms.activeTabAtom, "job:b")
        const moved = store.get(atoms.activeWorkspaceTabAtom)
        store.set(atoms.workspaceActionAtom, { type: "move", group: "primary", tabId: "job:b", target: "secondary" })
        expect(store.get(atoms.workspaceAtom).groups.primary.activeId).toBe("job:c")
        expect(store.get(atoms.activeWorkspaceTabAtom)).toBe(moved)
        expectWorkspaceDerived(store)
        store.set(atoms.workspaceActionAtom, { type: "move", group: "primary", tabId: "job:a", target: "secondary" })
        expect(store.get(atoms.workspaceAtom).groups.primary.activeId).toBe("job:c")
        store.set(atoms.workspaceActionAtom, { type: "move", group: "secondary", tabId: "job:a", target: "primary" })
        expect(store.get(atoms.workspaceAtom).groups.secondary.activeId).toBe("job:b")
        expect(store.get(atoms.activeTabAtom)).toBe("job:a")
        expect(store.get(detail.stage)).toBe("parse")
        expect(store.get(logs.search)).toBe("retained")
        expectWorkspaceDerived(store)
    })

    test("moving the sole secondary tab empties and folds its source and selects its destination", () => {
        const store = createStore()
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("a")), target: "secondary" })
        expect(store.get(atoms.secondaryCollapsedAtom)).toBe(false)
        store.set(atoms.workspaceActionAtom, { type: "move", group: "secondary", tabId: "job:a", target: "primary" })
        expect(store.get(atoms.workspaceAtom).groups.secondary).toEqual({ tabs: [], activeId: null })
        expect(store.get(atoms.secondaryCollapsedAtom)).toBe(true)
        expect(store.get(atoms.activeTabAtom)).toBe("job:a")
        store.set(atoms.workspaceActionAtom, { type: "move", group: "primary", tabId: "job:a", target: "secondary" })
        expect(store.get(atoms.workspaceAtom).groups.primary.activeId).toBe("tab:home")
        expect(store.get(atoms.tabItemsAtom).map((tab) => tab.id)).toEqual(["job:a"])
        expect(store.get(atoms.secondaryCollapsedAtom)).toBe(false)
        expectWorkspaceDerived(store)
    })

    test("missing selections, missing closes and same-group moves are no-ops", () => {
        const store = createStore()
        const before = store.get(atoms.workspaceAtom)
        const actions: WorkspaceAction[] = [
            { type: "select", group: "primary", tabId: "missing" },
            { type: "close", group: "secondary", tabId: "missing" },
            { type: "move", group: "secondary", tabId: "tab:explorer", target: "secondary" }
        ]
        for (const action of actions) {
            store.set(atoms.workspaceActionAtom, action)
            expect(store.get(atoms.workspaceAtom)).toBe(before)
            expectWorkspaceDerived(store)
        }
    })
})

describe("navigation destinations in the shared workspace", () => {
    test("Home and Dashboard aliases deduplicate to the same pinned primary tab", () => {
        const store = createStore()
        const dashboard = store.get(atoms.workspaceAtom).groups.primary.tabs[0]
        expect(navigationTab("tab:home")).toEqual(navigationTab("tab:home"))
        expect(navigationTab("tab:home")).toEqual(dashboard)
        expect(navigation.find((item) => item.id === "tab:home")?.content).toBe(HomeTab)
        for (const id of ["tab:home", "tab:home", "tab:home"] as const) {
            store.set(atoms.workspaceActionAtom, { type: "focus", group: "secondary" })
            store.set(atoms.workspaceActionAtom, { type: "open", tab: navigationTab(id), target: "secondary" })
            expect(store.get(atoms.workspaceAtom).activeGroup).toBe("primary")
            expect(store.get(atoms.activeWorkspaceTabAtom)).toBe(dashboard)
            expect(store.get(atoms.workspaceAtom).groups.primary.tabs).toEqual([dashboard])
            expectWorkspaceDerived(store)
        }
    })

    test.each(["jobs", "settings"] as const)(
        "%s is a valid destination even though it is absent from the sidebar",
        (id) => {
            const store = createStore()
            const destination: TabID = id
            expect(navigation.some((item) => (item.id as TabID) === destination)).toBe(false)
            const tab = navigationTab(destination)
            expect(tab).toEqual({
                id,
                title: id === "jobs" ? "Conversion jobs" : "Settings",
                view: id === "jobs" ? JobTab : SettingsTab,
                pinned: false
            })
            store.set(atoms.workspaceActionAtom, { type: "open", tab, target: "secondary" })
            expect(store.get(atoms.activeWorkspaceTabAtom)).toEqual(tab)
            store.set(atoms.workspaceActionAtom, { type: "open", tab: navigationTab(destination), target: "primary" })
            expect(store.get(atoms.workspaceAtom).activeGroup).toBe("secondary")
            expect(store.get(atoms.tabItemsAtom).filter((item) => item.id === id)).toHaveLength(1)
            expectWorkspaceDerived(store)
        }
    )

    test("sidebar icons are actual typed Lucide components rather than icon names", () => {
        expect(navigation.map((item) => item.icon)).toEqual([House, BookSearch])
        for (const item of navigation) {
            const Icon: LucideIcon = item.icon
            const element = createElement(Icon, { "aria-hidden": true, strokeWidth: 1.5 })
            expect(element.type).toBe(Icon)
            expect(typeof element.type).not.toBe("string")
        }
    })
})

describe("independent Jotai store lifetimes", () => {
    test("workspace actions and panel changes do not affect another createStore", () => {
        const first = createStore()
        const second = createStore()
        const originalWorkspace = second.get(atoms.workspaceAtom)
        const originalPanels = panelState(second)
        first.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("a")), target: "secondary" })
        changePanels(first)
        expect(second.get(atoms.workspaceAtom)).toBe(originalWorkspace)
        expect(panelState(second)).toEqual(originalPanels)
        second.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("b")) })
        expect(first.get(atoms.activeTabAtom)).toBe("job:a")
        expect(second.get(atoms.activeTabAtom)).toBe("job:b")
        expectWorkspaceDerived(first)
        expectWorkspaceDerived(second)
    })

    test("backend controllers and conversion clients are stable within a store but not shared between stores", () => {
        const first = createStore()
        const second = createStore()
        const controller = first.get(atoms.backendControllerAtom)
        const client = first.get(atoms.conversionClientAtom)
        expect(controller).toBeInstanceOf(BackendPolling)
        expect(client).toBeInstanceOf(ConversionClient)
        expect(first.get(atoms.backendControllerAtom)).toBe(controller)
        expect(first.get(atoms.conversionClientAtom)).toBe(client)
        expect(second.get(atoms.backendControllerAtom)).not.toBe(controller)
        expect(second.get(atoms.conversionClientAtom)).not.toBe(client)
        expect(second.get(atoms.conversionClientAtom).getSnapshot()).not.toBe(client.getSnapshot())
        // Pausing an unstarted controller changes local state without making an RPC.
        controller.pause()
        expect(controller.getSnapshot().isAutoEnabled).toBe(false)
        expect(second.get(atoms.backendControllerAtom).getSnapshot().isAutoEnabled).toBe(true)
        first.set(atoms.jobsQueryAtom, "unrelated")
        expect(first.get(atoms.backendControllerAtom)).toBe(controller)
        expect(first.get(atoms.conversionClientAtom)).toBe(client)
        first.set(atoms.applyRequestTokenAtom, "first-identity")
        expect(first.get(atoms.conversionClientAtom)).not.toBe(client)
        expect(second.get(atoms.requestTokenAtom)).toBe("")
    })

    test("backend and conversion snapshots stay scoped to their originating store", () => {
        const first = createStore()
        const second = createStore()
        setBackend(first, ready)
        first.set(atoms.lastEndpointAtom, ready.url)
        const value = publishJobs(first, [job("a")])
        expect(first.get(atoms.conversionSnapshotAtom)).toBe(value)
        expect(second.get(atoms.backendAtom)).toEqual(starting)
        expect(second.get(atoms.lastEndpointAtom)).toBeNull()
        expect(second.get(atoms.conversionEndpointAtom)).toBeNull()
        expect(second.get(atoms.conversionSnapshotAtom)).toEqual(snapshot())
        second.set(atoms.conversionSnapshotSourceAtom, {
            client: first.get(atoms.conversionClientAtom),
            snapshot: value
        })
        expect(second.get(atoms.conversionSnapshotAtom)).toEqual(snapshot())
    })

    test("drafts, uploads, job views and stable detail/log families are store-isolated", () => {
        const first = createStore()
        const second = createStore()
        seedConversionViews(first)
        expectConversionViewsReset(second)
        expect(second.get(atoms.conversionSessionAtom)).toBe(0)
        second.set(atoms.conversionDraftAtom, (previous) => ({ ...previous, name: "Second draft" }))
        second.set(atoms.conversionLogAtomsFor("0:detail:a").search, "second search")
        expect(first.get(atoms.conversionDraftAtom)).toEqual(draft())
        expect(first.get(atoms.fileUploadAtom).files).toHaveLength(1)
        expect(first.get(atoms.conversionLogAtomsFor("0:detail:a").search)).toBe("detail")
        first.set(atoms.resetConversionViewsAtom)
        expectConversionViewsReset(first)
        expect(second.get(atoms.conversionDraftAtom).name).toBe("Second draft")
        expect(second.get(atoms.conversionLogAtomsFor("0:detail:a").search)).toBe("second search")
        expect(second.get(atoms.conversionSessionAtom)).toBe(0)
    })

    test("backend event history, deduplication and sequence are store-isolated", () => {
        const first = createStore()
        const second = createStore()
        first.set(atoms.recordBackendEventAtom, ready)
        expect(second.get(atoms.backendEventsAtom)).toEqual([])
        second.set(atoms.recordBackendEventAtom, { ...ready })
        expect(first.get(atoms.backendEventsAtom)[0].id).toBe(1)
        expect(second.get(atoms.backendEventsAtom)[0].id).toBe(1)
        first.set(atoms.clearBackendEventsAtom)
        expect(second.get(atoms.backendEventsAtom)).toHaveLength(1)
    })
})

describe("workspace and conversion reset boundaries", () => {
    test("resetWorkspace restores every panel and fresh workspace without resetting conversion or runtime state", () => {
        const store = createStore()
        const original = store.get(atoms.workspaceAtom)
        seedConversionViews(store)
        changePanels(store)
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("a")), target: "secondary" })
        store.set(atoms.themeAtom, "dark")
        store.set(atoms.requestTokenAtom, "identity")
        store.set(atoms.tokenDraftAtom, "unfinished token")
        setBackend(store, ready)
        store.set(atoms.recordBackendEventAtom, ready)
        const client = store.get(atoms.conversionClientAtom)
        const controller = store.get(atoms.backendControllerAtom)
        const value = publishJobs(store, [job("a")])
        const retainedDraft = store.get(atoms.conversionDraftAtom)
        const retainedUpload = store.get(atoms.fileUploadAtom)
        withRevocationSpy((revoke) => {
            store.set(atoms.resetWorkspaceAtom)
            expect(revoke).not.toHaveBeenCalled()
        })
        const reset = store.get(atoms.workspaceAtom)
        expect(reset).toEqual(createWorkspaceState())
        expect(reset).not.toBe(original)
        expect(reset.groups.primary.tabs).not.toBe(original.groups.primary.tabs)
        expect(panelState(store)).toEqual(panelState(createStore()))
        expect(store.get(atoms.eventsOpenAtom)).toBe(false)
        expect(store.get(atoms.conversionDraftAtom)).toBe(retainedDraft)
        expect(store.get(atoms.fileUploadAtom)).toBe(retainedUpload)
        expect(store.get(atoms.conversionStepAtom)).toBe(2)
        expect(store.get(atoms.jobsQueryAtom)).toBe("source")
        expect(store.get(atoms.inspectedJobIdAtom)).toBe("a")
        expect(store.get(atoms.conversionDetailAtomsFor("0:a").stage)).toBe("parse")
        expect(store.get(atoms.conversionLogAtomsFor("0:dock:a").search)).toBe("dock")
        expect(store.get(atoms.conversionSessionAtom)).toBe(0)
        expect(store.get(atoms.requestTokenAtom)).toBe("identity")
        expect(store.get(atoms.tokenDraftAtom)).toBe("unfinished token")
        expect(store.get(atoms.themeAtom)).toBe("dark")
        expect(store.get(atoms.backendAtom)).toBe(ready)
        expect(store.get(atoms.backendEventsAtom)).toHaveLength(1)
        expect(store.get(atoms.conversionClientAtom)).toBe(client)
        expect(store.get(atoms.backendControllerAtom)).toBe(controller)
        expect(store.get(atoms.conversionSnapshotAtom)).toBe(value)
        expectWorkspaceDerived(store)
        store.set(atoms.resetWorkspaceAtom)
        expect(store.get(atoms.workspaceAtom)).not.toBe(reset)
    })

    test("events visibility follows its placement and expansion, and showEvents reveals its panel", () => {
        const store = createStore()
        expect(store.get(atoms.eventsOpenAtom)).toBe(false)
        store.set(atoms.showEventsAtom)
        expect(store.get(atoms.eventsOpenAtom)).toBe(true)
        store.set(atoms.panelActionAtom, { type: "close", id: "dock-events" })
        expect(store.get(atoms.eventsOpenAtom)).toBe(false)
        store.set(atoms.dockCollapsedAtom, true)
        store.set(atoms.showEventsAtom)
        expect(store.get(atoms.dockCollapsedAtom)).toBe(false)
        expect(store.get(atoms.eventsOpenAtom)).toBe(true)
        store.set(atoms.panelActionAtom, { type: "move", id: "dock-events", area: "sidebar" })
        store.set(atoms.sidebarCollapsedAtom, true)
        expect(store.get(atoms.eventsOpenAtom)).toBe(false)
        store.set(atoms.showEventsAtom)
        expect(store.get(atoms.sidebarCollapsedAtom)).toBe(false)
        expect(store.get(atoms.eventsOpenAtom)).toBe(true)
    })

    test("draft and upload survive tab changes, closing jobs, moves and panel folds", () => {
        const store = createStore()
        const retainedDraft = draft()
        const retainedUpload = upload(["blob:retained"])
        store.set(atoms.conversionDraftAtom, retainedDraft)
        store.set(atoms.fileUploadAtom, retainedUpload)
        store.set(atoms.conversionStepAtom, 1)
        withRevocationSpy((revoke) => {
            const actions: WorkspaceAction[] = [
                { type: "open", tab: jobWorkspaceTab(job("a")) },
                { type: "move", group: "primary", tabId: "job:a", target: "secondary" },
                { type: "close", group: "secondary", tabId: "job:a" },
                { type: "focus", group: "primary" }
            ]
            for (const action of actions) {
                store.set(atoms.workspaceActionAtom, action)
                expect(store.get(atoms.conversionDraftAtom)).toBe(retainedDraft)
                expect(store.get(atoms.fileUploadAtom)).toBe(retainedUpload)
            }
            changePanels(store)
            store.set(atoms.resetWorkspaceAtom)
            expect(store.get(atoms.conversionDraftAtom)).toBe(retainedDraft)
            expect(store.get(atoms.fileUploadAtom)).toBe(retainedUpload)
            expect(store.get(atoms.conversionStepAtom)).toBe(1)
            expect(revoke).not.toHaveBeenCalled()
        })
    })

    test("resetConversionForm revokes only discarded blob previews once and leaves other stores and views intact", () => {
        const store = createStore()
        const other = createStore()
        seedConversionViews(store)
        const otherUpload = upload(["blob:other-store"])
        other.set(atoms.fileUploadAtom, otherUpload)
        other.set(atoms.conversionDraftAtom, draft())
        store.set(
            atoms.fileUploadAtom,
            upload([
                "blob:first",
                "blob:second",
                "https://example.invalid/preview",
                "data:text/plain,source",
                undefined
            ])
        )
        withRevocationSpy((revoke) => {
            store.set(atoms.resetConversionFormAtom)
            expect(revoke.mock.calls).toEqual([["blob:first"], ["blob:second"]])
            expectFormReset(store)
            const resetDraft = store.get(atoms.conversionDraftAtom)
            expect(resetDraft).not.toBe(atoms.initialConversionDraft)
            store.set(atoms.resetConversionFormAtom)
            expect(revoke).toHaveBeenCalledTimes(2)
            expect(store.get(atoms.conversionDraftAtom)).not.toBe(resetDraft)
        })
        expect(other.get(atoms.fileUploadAtom)).toBe(otherUpload)
        expect(other.get(atoms.conversionDraftAtom)).toEqual(draft())
        expect(store.get(atoms.jobsQueryAtom)).toBe("source")
        expect(store.get(atoms.conversionDetailAtomsFor("0:a").stage)).toBe("parse")
        expect(store.get(atoms.conversionSessionAtom)).toBe(0)
    })

    test("resetConversionViews clears form and every cached job field, advancing only its own session", () => {
        const store = createStore()
        const other = createStore()
        seedConversionViews(store)
        seedConversionViews(other)
        store.set(atoms.conversionSessionAtom, 7)
        const detail = atoms.conversionDetailAtomsFor("7:b")
        const logs = atoms.conversionLogAtomsFor("7:dock:b")
        store.set(detail.stage, "validate")
        store.set(logs.search, "another job")
        store.set(atoms.resetConversionViewsAtom)
        expectConversionViewsReset(store)
        expect(store.get(detail.stage)).toBeNull()
        expect(store.get(logs.search)).toBe("")
        expect(store.get(atoms.conversionSessionAtom)).toBe(8)
        expect(other.get(atoms.jobsQueryAtom)).toBe("source")
        expect(other.get(atoms.conversionSessionAtom)).toBe(0)
        store.set(atoms.resetConversionViewsAtom)
        expect(store.get(atoms.conversionSessionAtom)).toBe(9)
    })
})

describe("identity reset job-tab privacy", () => {
    test.each(["token", "endpoint/reset action"] as const)(
        "%s removes all job metadata from both groups, including pinned and non-job-view tabs",
        (reset) => {
            const store = createStore()
            const other = createStore()
            setBackend(store, ready)
            store.set(atoms.lastEndpointAtom, ready.url)
            store.set(atoms.applyRequestTokenAtom, "previous-identity")
            const initial = createWorkspaceState()
            const reference: WorkspaceTab = {
                id: "document:reference",
                title: "Reference",
                view: ExploreTab,
                pinned: false
            }
            const settings = navigationTab("settings")
            const jobs = navigationTab("jobs")
            const retainedExplorer: WorkspaceTab = {
                id: "retained-explorer",
                title: "Other explorer",
                view: ExploreTab,
                pinned: true
            }
            const previousWorkspace = {
                groups: {
                    primary: {
                        tabs: [
                            initial.groups.primary.tabs[0],
                            settings,
                            {
                                id: "private-primary",
                                title: "Previous user's job name",
                                view: JobDetailTab,
                                pinned: true
                            },
                            jobWorkspaceTab(job("private-a")),
                            {
                                id: "private-empty-id",
                                title: "Previous user's metadata",
                                view: SettingsTab,
                                pinned: true,
                                jobId: ""
                            },
                            jobs
                        ],
                        activeId: "private-primary"
                    },
                    secondary: {
                        tabs: [
                            reference,
                            {
                                id: "private-secondary",
                                title: "Previous user's other job",
                                view: ExploreTab,
                                pinned: true,
                                jobId: "private-b"
                            },
                            jobWorkspaceTab(job("private-c")),
                            retainedExplorer
                        ],
                        activeId: "private-secondary"
                    }
                },
                activeGroup: "secondary" as const
            }
            store.set(atoms.workspaceAtom, previousWorkspace)
            other.set(atoms.workspaceAtom, previousWorkspace)
            changePanels(store)
            store.set(atoms.inspectedJobIdAtom, "private-b")
            store.set(atoms.jobsSelectedIdAtom, "private-a")
            publishJobs(store, [job("private-a"), job("private-b"), job("private-c")])
            expect(store.get(atoms.selectedJobAtom)?.id).toBe("private-b")
            const panels = panelState(store)
            const session = store.get(atoms.conversionSessionAtom)
            if (reset === "token") {
                store.set(atoms.applyRequestTokenAtom, "new-identity")
            } else {
                const endpoint = "http://127.0.0.1:9000"
                setBackend(store, { ...ready, url: endpoint })
                store.set(atoms.lastEndpointAtom, endpoint)
                // Endpoint changes invoke this action from useConversionJobs, not from an atom read.
                store.set(atoms.resetConversionViewsAtom)
            }
            const workspace = store.get(atoms.workspaceAtom)
            expect(workspace.groups.primary.tabs).toEqual([initial.groups.primary.tabs[0], settings, jobs])
            expect(workspace.groups.secondary.tabs).toEqual([reference, retainedExplorer])
            expect(workspace.groups.primary.activeId).toBe("jobs")
            expect(workspace.groups.secondary.activeId).toBe("retained-explorer")
            expect(workspace.activeGroup).toBe("secondary")
            for (const tab of Object.values(workspace.groups).flatMap((group) => group.tabs)) {
                expect(tab.view).not.toBe(JobDetailTab)
                expect(tab.jobId).toBeUndefined()
                expect(tab.title).not.toContain("Previous user's")
            }
            expect(workspace.groups.primary.tabs[1]).toBe(settings)
            expect(workspace.groups.primary.tabs[2]).toBe(jobs)
            expect(workspace.groups.secondary.tabs[1]).toBe(retainedExplorer)
            expect(panelState(store)).toEqual(panels)
            expect(store.get(atoms.inspectedJobIdAtom)).toBeNull()
            expect(store.get(atoms.jobsSelectedIdAtom)).toBeNull()
            expect(store.get(atoms.selectedJobAtom)).toBeNull()
            expect(store.get(atoms.conversionSnapshotAtom)).toEqual(snapshot())
            expect(store.get(atoms.conversionSessionAtom)).toBe(session + 1)
            expect(other.get(atoms.workspaceAtom)).toBe(previousWorkspace)
            expect(other.get(atoms.workspaceAtom).groups.secondary.activeId).toBe("private-secondary")
            expectWorkspaceDerived(store)
        }
    )

    for (const reset of ["token", "reset action"] as const) {
        test.each(["right", "left", "retained", "empty"] as const)(
            `${reset} preserves or falls back to the %s selection after removing job tabs`,
            (selection) => {
                const store = createStore()
                const initial = createWorkspaceState()
                const explorer = navigationTab("tab:explorer")
                const settings = navigationTab("settings")
                const a = { ...jobWorkspaceTab(job("a")), pinned: true }
                const b = { ...jobWorkspaceTab(job("b")), pinned: true }
                const cases = {
                    right: { tabs: [explorer, a, b, settings], activeId: a.id, expectedId: settings.id },
                    left: { tabs: [explorer, settings, a, b], activeId: b.id, expectedId: settings.id },
                    retained: { tabs: [explorer, a, settings, b], activeId: settings.id, expectedId: settings.id },
                    empty: { tabs: [a, b], activeId: b.id, expectedId: null }
                }
                const chosen = cases[selection]
                store.set(atoms.workspaceAtom, {
                    groups: { ...initial.groups, secondary: { tabs: chosen.tabs, activeId: chosen.activeId } },
                    activeGroup: "secondary"
                })
                store.set(atoms.inspectedJobIdAtom, "a")
                if (reset === "token") store.set(atoms.applyRequestTokenAtom, "new-identity")
                else store.set(atoms.resetConversionViewsAtom)
                const workspace = store.get(atoms.workspaceAtom)
                expect(workspace.groups.primary).toEqual(initial.groups.primary)
                expect(workspace.groups.secondary.tabs).toEqual(selection === "empty" ? [] : [explorer, settings])
                expect(workspace.groups.secondary.activeId).toBe(chosen.expectedId)
                expect(workspace.activeGroup).toBe(selection === "empty" ? "primary" : "secondary")
                expect(store.get(atoms.secondaryCollapsedAtom)).toBe(selection === "empty")
                expect(store.get(atoms.activeTabAtom)).toBe(selection === "empty" ? "tab:home" : chosen.expectedId)
                expect(store.get(atoms.activeWorkspaceTabAtom)).toBe(selection === "empty" ? initial.groups.primary.tabs[0] : settings)
                expect(store.get(atoms.inspectedJobIdAtom)).toBeNull()
                expectWorkspaceDerived(store)
            }
        )
    }
})

describe("central detail and log atom families", () => {
    test("returns stable atom bundles per key with independent defaults and functional field updates", () => {
        const store = createStore()
        const detail = atoms.conversionDetailAtomsFor("0:a")
        const logs = atoms.conversionLogAtomsFor("0:detail:a")
        expect(atoms.conversionDetailAtomsFor("0:a")).toBe(detail)
        expect(atoms.conversionLogAtomsFor("0:detail:a")).toBe(logs)
        expect(atoms.conversionDetailAtomsFor("0:b")).not.toBe(detail)
        expect(atoms.conversionLogAtomsFor("0:detail:b")).not.toBe(logs)
        expect(store.get(detail.stage)).toBeNull()
        expect(store.get(logs.selectedLevels)).toEqual(defaultLevels)
        store.set(detail.stage, "parse")
        store.set(detail.downloading, (previous) => !previous)
        store.set(detail.downloadError, "download error")
        store.set(logs.search, (previous) => `${previous}parse`)
        store.set(logs.selectedLevels, (previous) => previous.filter((level) => level !== "debug"))
        store.set(logs.copyState, "copied")
        store.set(logs.copiedText, "copied logs")
        expect(store.get(detail.stage)).toBe("parse")
        expect(store.get(detail.downloading)).toBe(true)
        expect(store.get(detail.downloadError)).toBe("download error")
        expect(store.get(logs.search)).toBe("parse")
        expect(store.get(logs.selectedLevels)).toEqual(["info", "warning", "error", "unclassified"])
        expect(store.get(logs.copyState)).toBe("copied")
        expect(store.get(logs.copiedText)).toBe("copied logs")
        expect(store.get(logs.copyError)).toBeNull()
        expect(store.get(atoms.conversionDetailAtomsFor("0:b").stage)).toBeNull()
        expect(store.get(atoms.conversionLogAtomsFor("0:detail:b").selectedLevels)).toEqual(defaultLevels)
    })

    test("detail and dock filters, clipboard fields, jobs and session keys remain independent", () => {
        const store = createStore()
        const detail = atoms.conversionLogAtomsFor("0:detail:a")
        const dock = atoms.conversionLogAtomsFor("0:dock:a")
        store.set(detail.search, "parse")
        store.set(detail.selectedLevels, ["error"])
        store.set(detail.copyState, "copying")
        store.set(detail.copyError, "detail clipboard error")
        store.set(dock.search, "validate")
        store.set(dock.selectedLevels, ["warning", "info"])
        store.set(dock.copyState, "copied")
        store.set(dock.copiedText, "dock text")
        expect(store.get(detail.search)).toBe("parse")
        expect(store.get(detail.selectedLevels)).toEqual(["error"])
        expect(store.get(detail.copyState)).toBe("copying")
        expect(store.get(detail.copyError)).toBe("detail clipboard error")
        expect(store.get(detail.copiedText)).toBeNull()
        expect(store.get(dock.search)).toBe("validate")
        expect(store.get(dock.selectedLevels)).toEqual(["warning", "info"])
        expect(store.get(dock.copyError)).toBeNull()
        for (const key of ["0:detail:b", "0:dock:b", "1:detail:a", "1:dock:a"]) {
            const untouched = atoms.conversionLogAtomsFor(key)
            expect(store.get(untouched.search)).toBe("")
            expect(store.get(untouched.selectedLevels)).toEqual(defaultLevels)
            expect(store.get(untouched.copyState)).toBe("idle")
        }
    })
})

describe("request token normalization and identity resets", () => {
    test.each([
        ["  token-a  ", "token-a"],
        ["  Bearer token-a  ", "token-a"],
        ["bEaReR\t token-a", "token-a"],
        ["BearerToken", "BearerToken"],
        ["   ", ""]
    ])("normalizes %j to %j and clears the token draft", (input, expected) => {
        const store = createStore()
        store.set(atoms.tokenDraftAtom, "pending edit")
        store.set(atoms.applyRequestTokenAtom, input)
        expect(store.get(atoms.requestTokenAtom)).toBe(expected)
        expect(store.get(atoms.tokenDraftAtom)).toBe("")
        expect(store.get(atoms.conversionSessionAtom)).toBe(expected ? 1 : 0)
    })

    test("an equal normalized token clears only its draft and retains client, form, uploads and job fields", () => {
        const store = createStore()
        store.set(atoms.applyRequestTokenAtom, "token-a")
        seedConversionViews(store)
        store.set(atoms.fileUploadAtom, upload(["blob:equal-token"]))
        store.set(atoms.tokenDraftAtom, "  Bearer token-a  ")
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("a")) })
        store.set(atoms.workspaceActionAtom, {
            type: "open",
            tab: { ...jobWorkspaceTab(job("b")), pinned: true },
            target: "secondary"
        })
        const workspace = store.get(atoms.workspaceAtom)
        const client = store.get(atoms.conversionClientAtom)
        const retainedDraft = store.get(atoms.conversionDraftAtom)
        const retainedUpload = store.get(atoms.fileUploadAtom)
        const value = publishJobs(store, [job("a")])
        withRevocationSpy((revoke) => {
            store.set(atoms.applyRequestTokenAtom, "  bEaReR token-a  ")
            expect(revoke).not.toHaveBeenCalled()
        })
        expect(store.get(atoms.requestTokenAtom)).toBe("token-a")
        expect(store.get(atoms.tokenDraftAtom)).toBe("")
        expect(store.get(atoms.conversionSessionAtom)).toBe(1)
        expect(store.get(atoms.conversionClientAtom)).toBe(client)
        expect(store.get(atoms.conversionSnapshotAtom)).toBe(value)
        expect(store.get(atoms.conversionDraftAtom)).toBe(retainedDraft)
        expect(store.get(atoms.fileUploadAtom)).toBe(retainedUpload)
        expect(store.get(atoms.conversionStepAtom)).toBe(2)
        expect(store.get(atoms.jobsQueryAtom)).toBe("source")
        expect(store.get(atoms.inspectedJobIdAtom)).toBe("a")
        expect(store.get(atoms.conversionDetailAtomsFor("0:a").stage)).toBe("parse")
        expect(store.get(atoms.conversionLogAtomsFor("0:detail:a").search)).toBe("detail")
        expect(store.get(atoms.workspaceAtom)).toBe(workspace)
        expect(store.get(atoms.workspaceAtom).groups.primary.tabs.some((tab) => tab.jobId === "a")).toBe(true)
        expect(
            store.get(atoms.workspaceAtom).groups.secondary.tabs.some((tab) => tab.jobId === "b" && tab.pinned)
        ).toBe(true)
        expectWorkspaceDerived(store)
    })

    test("a changed token resets conversion state, revokes previews and advances the session without resetting layout", () => {
        const store = createStore()
        const other = createStore()
        seedConversionViews(store)
        store.set(atoms.fileUploadAtom, upload(["blob:identity-change"]))
        store.set(atoms.tokenDraftAtom, "new identity")
        changePanels(store)
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("a")) })
        const workspace = store.get(atoms.workspaceAtom)
        const panels = panelState(store)
        const client = store.get(atoms.conversionClientAtom)
        withRevocationSpy((revoke) => {
            store.set(atoms.applyRequestTokenAtom, " Bearer token-b ")
            expect(revoke.mock.calls).toEqual([["blob:identity-change"]])
        })
        expectConversionViewsReset(store)
        expect(store.get(atoms.requestTokenAtom)).toBe("token-b")
        expect(store.get(atoms.tokenDraftAtom)).toBe("")
        expect(store.get(atoms.conversionSessionAtom)).toBe(1)
        expect(store.get(atoms.conversionClientAtom)).not.toBe(client)
        expect(store.get(atoms.workspaceAtom)).toEqual(createWorkspaceState())
        expect(store.get(atoms.workspaceAtom).groups.primary.tabs[0]).toBe(workspace.groups.primary.tabs[0])
        expect(store.get(atoms.inspectedJobIdAtom)).toBeNull()
        expect(panelState(store)).toEqual(panels)
        expect(other.get(atoms.requestTokenAtom)).toBe("")
        expect(other.get(atoms.conversionSessionAtom)).toBe(0)
    })

    test("clearing an existing identity resets once while reapplying an empty token does not", () => {
        const store = createStore()
        store.set(atoms.applyRequestTokenAtom, "token-a")
        seedConversionViews(store)
        store.set(atoms.applyRequestTokenAtom, "  ")
        expectConversionViewsReset(store)
        expect(store.get(atoms.requestTokenAtom)).toBe("")
        expect(store.get(atoms.conversionSessionAtom)).toBe(2)
        store.set(atoms.conversionDraftAtom, draft())
        store.set(atoms.tokenDraftAtom, "cancelled edit")
        store.set(atoms.applyRequestTokenAtom, "")
        expect(store.get(atoms.conversionDraftAtom)).toEqual(draft())
        expect(store.get(atoms.conversionSessionAtom)).toBe(2)
        expect(store.get(atoms.tokenDraftAtom)).toBe("")
    })
})

describe("conversion snapshot ownership", () => {
    test("accepts only the current client's snapshot, not a null source or a lookalike client", () => {
        const store = createStore()
        setBackend(store, ready)
        store.set(atoms.applyRequestTokenAtom, "token-a")
        const current = store.get(atoms.conversionClientAtom)
        const value = snapshot([job("a")])
        store.set(atoms.conversionSnapshotSourceAtom, { client: null, snapshot: value })
        expect(store.get(atoms.conversionSnapshotAtom)).toBe(current.getSnapshot())
        store.set(atoms.conversionSnapshotSourceAtom, {
            client: new ConversionClient(ready.url, "token-a"),
            snapshot: value
        })
        expect(store.get(atoms.conversionSnapshotAtom)).toBe(current.getSnapshot())
        store.set(atoms.conversionSnapshotSourceAtom, { client: current, snapshot: value })
        expect(store.get(atoms.conversionSnapshotAtom)).toBe(value)
    })

    test.each(["token", "endpoint"] as const)(
        "a changed %s rejects old and late snapshots until the new client publishes",
        (identity) => {
            const store = createStore()
            setBackend(store, ready)
            store.set(atoms.applyRequestTokenAtom, "token-a")
            const previous = store.get(atoms.conversionClientAtom)
            publishJobs(store, [job("private-a")])
            if (identity === "token") store.set(atoms.applyRequestTokenAtom, "token-b")
            else setBackend(store, { ...ready, url: "http://127.0.0.1:9000" })
            const current = store.get(atoms.conversionClientAtom)
            expect(current).not.toBe(previous)
            expect(store.get(atoms.conversionSnapshotAtom)).toBe(current.getSnapshot())
            expect(store.get(atoms.conversionSnapshotAtom)).toEqual(snapshot())
            const late = {
                ...snapshot([job("late-private-a")]),
                isLoading: true,
                isSubmitting: true,
                error: "Old identity error"
            }
            store.set(atoms.conversionSnapshotSourceAtom, { client: previous, snapshot: late })
            expect(store.get(atoms.conversionSnapshotAtom)).toEqual(snapshot())
            const accepted = publishJobs(store, [job("public-b")])
            expect(store.get(atoms.conversionSnapshotAtom)).toBe(accepted)
            store.set(atoms.conversionSnapshotSourceAtom, { client: previous, snapshot: late })
            expect(store.get(atoms.conversionSnapshotAtom).jobs).not.toContainEqual(job("late-private-a"))
            expect(store.get(atoms.conversionSnapshotAtom)).toBe(current.getSnapshot())
        }
    )

    test("returning to an earlier token creates a new identity rather than exposing its old snapshot", () => {
        const store = createStore()
        store.set(atoms.applyRequestTokenAtom, "token-a")
        const original = store.get(atoms.conversionClientAtom)
        const originalSnapshot = publishJobs(store, [job("private-a")])
        store.set(atoms.applyRequestTokenAtom, "token-b")
        store.set(atoms.applyRequestTokenAtom, "token-a")
        expect(store.get(atoms.conversionClientAtom)).not.toBe(original)
        store.set(atoms.conversionSnapshotSourceAtom, { client: original, snapshot: originalSnapshot })
        expect(store.get(atoms.conversionSnapshotAtom)).toEqual(snapshot())
        expect(store.get(atoms.conversionSessionAtom)).toBe(3)
    })

    test("the remembered endpoint survives offline status without changing an otherwise equal client", () => {
        const store = createStore()
        expect(store.get(atoms.conversionEndpointAtom)).toBeNull()
        store.set(atoms.lastEndpointAtom, ready.url)
        expect(store.get(atoms.conversionEndpointAtom)).toBe(ready.url)
        setBackend(store, ready)
        const client = store.get(atoms.conversionClientAtom)
        const value = publishJobs(store, [job("a")])
        setBackend(store, { ...starting, state: "failed", error: "Restarting" })
        expect(store.get(atoms.conversionEndpointAtom)).toBe(ready.url)
        expect(store.get(atoms.conversionClientAtom)).toBe(client)
        expect(store.get(atoms.conversionSnapshotAtom)).toBe(value)
        setBackend(store, { ...ready, url: "http://127.0.0.1:9000" })
        expect(store.get(atoms.conversionEndpointAtom)).toBe("http://127.0.0.1:9000")
        expect(store.get(atoms.conversionClientAtom)).not.toBe(client)
        expect(store.get(atoms.lastEndpointAtom)).toBe(ready.url)
    })
})

describe("selected job derivation", () => {
    test("uses an inspected job off job tabs and prioritizes the active job tab across focus and moves", () => {
        const store = createStore()
        const a = job("a")
        const b = job("b")
        publishJobs(store, [a, b])
        expect(store.get(atoms.selectedJobAtom)).toBeNull()
        store.set(atoms.inspectedJobIdAtom, "b")
        expect(store.get(atoms.selectedJobAtom)).toBe(b)
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(a) })
        expect(store.get(atoms.selectedJobAtom)).toBe(a)
        store.set(atoms.workspaceActionAtom, { type: "focus", group: "secondary" })
        expect(store.get(atoms.selectedJobAtom)).toBe(b)
        store.set(atoms.workspaceActionAtom, { type: "move", group: "primary", tabId: "job:a", target: "secondary" })
        expect(store.get(atoms.selectedJobAtom)).toBe(a)
        store.set(atoms.workspaceActionAtom, { type: "close", group: "secondary", tabId: "job:a" })
        expect(store.get(atoms.selectedJobAtom)).toBe(b)
    })

    test("does not substitute the inspector's job when the active tab names a missing job", () => {
        const store = createStore()
        publishJobs(store, [job("b")])
        store.set(atoms.inspectedJobIdAtom, "b")
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(job("missing")) })
        expect(store.get(atoms.selectedJobAtom)).toBeNull()
        store.set(atoms.activeTabAtom, "tab:home")
        expect(store.get(atoms.selectedJobAtom)?.id).toBe("b")
        store.set(atoms.inspectedJobIdAtom, "also-missing")
        expect(store.get(atoms.selectedJobAtom)).toBeNull()
    })

    test("follows current snapshots and never derives a selected job from a previous identity", () => {
        const store = createStore()
        const a = job("a")
        const previous = store.get(atoms.conversionClientAtom)
        const oldSnapshot = publishJobs(store, [a])
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(a) })
        expect(store.get(atoms.selectedJobAtom)).toBe(a)
        const updated = { ...a, status: "running" as const }
        publishJobs(store, [updated])
        expect(store.get(atoms.selectedJobAtom)).toBe(updated)
        publishJobs(store, [])
        expect(store.get(atoms.selectedJobAtom)).toBeNull()
        store.set(atoms.conversionSnapshotSourceAtom, { client: previous, snapshot: oldSnapshot })
        store.set(atoms.applyRequestTokenAtom, "another-identity")
        expect(store.get(atoms.activeTabAtom)).toBe("tab:home")
        expect(store.get(atoms.activeWorkspaceTabAtom)?.jobId).toBeUndefined()
        expect(store.get(atoms.inspectedJobIdAtom)).toBeNull()
        expect(store.get(atoms.selectedJobAtom)).toBeNull()
        const replacement = { ...job("a"), name: "New identity's job" }
        publishJobs(store, [replacement])
        expect(store.get(atoms.selectedJobAtom)).toBeNull()
        store.set(atoms.workspaceActionAtom, { type: "open", tab: jobWorkspaceTab(replacement) })
        expect(store.get(atoms.selectedJobAtom)).toBe(replacement)
    })
})

describe("store backend event history", () => {
    test("records only changed statuses, newest first, with sequence IDs and bounded timestamps", () => {
        const store = createStore()
        const before = Date.now()
        store.set(atoms.recordBackendEventAtom, starting)
        const initialEvents = store.get(atoms.backendEventsAtom)
        store.set(atoms.recordBackendEventAtom, { ...starting })
        expect(store.get(atoms.backendEventsAtom)).toBe(initialEvents)
        store.set(atoms.recordBackendEventAtom, ready)
        store.set(atoms.recordBackendEventAtom, { ...ready })
        const events = store.get(atoms.backendEventsAtom)
        expect(events.map((event) => event.id)).toEqual([2, 1])
        expect(events.map((event) => event.level)).toEqual(["success", "info"])
        expect(events[0].message).toContain(ready.url!)
        for (const event of events) {
            expect(event.timestamp).toBeGreaterThanOrEqual(before)
            expect(event.timestamp).toBeLessThanOrEqual(Date.now())
        }
    })

    test.each([
        { state: "stopped" },
        { url: "http://127.0.0.1:9000" },
        { error: "Changed error" },
        { authRequired: true }
    ] satisfies Partial<SidecarStatus>[])("a changed %j field records exactly one additional event", (change) => {
        const store = createStore()
        store.set(atoms.recordBackendEventAtom, ready)
        const changed = { ...ready, ...change }
        store.set(atoms.recordBackendEventAtom, changed)
        store.set(atoms.recordBackendEventAtom, { ...changed })
        expect(store.get(atoms.backendEventsAtom).map((event) => event.id)).toEqual([2, 1])
    })

    test("keeps only the newest 50 events without reusing dropped sequence IDs", () => {
        const store = createStore()
        for (let index = 1; index <= 60; index++) {
            store.set(atoms.recordBackendEventAtom, { ...starting, state: "failed", error: `Failure ${index}` })
        }
        const events = store.get(atoms.backendEventsAtom)
        expect(events).toHaveLength(50)
        expect(events.map((event) => event.id)).toEqual(Array.from({ length: 50 }, (_, index) => 60 - index))
        expect(events[0].message).toBe("Failure 60")
        expect(events[49].message).toBe("Failure 11")
        store.set(atoms.recordBackendEventAtom, { ...starting, state: "failed", error: "Failure 60" })
        expect(store.get(atoms.backendEventsAtom)).toBe(events)
    })

    test("clearing events preserves the last observed status and monotonically increasing sequence", () => {
        const store = createStore()
        store.set(atoms.recordBackendEventAtom, ready)
        store.set(atoms.clearBackendEventsAtom)
        expect(store.get(atoms.backendEventsAtom)).toEqual([])
        store.set(atoms.recordBackendEventAtom, { ...ready })
        expect(store.get(atoms.backendEventsAtom)).toEqual([])
        store.set(atoms.recordBackendEventAtom, { ...starting, state: "stopped" })
        expect(store.get(atoms.backendEventsAtom)).toHaveLength(1)
        expect(store.get(atoms.backendEventsAtom)[0]).toMatchObject({ id: 2, level: "warning" })
    })
})
