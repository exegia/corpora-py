import { atom, createStore, type Atom, type PrimitiveAtom } from "jotai"
import { BackendPolling, type BackendPollingSnapshot } from "@/lib/backend-polling"
import { ConversionClient, type ConversionSnapshot } from "@/lib/conversion-client"
import { describeBackendEvent, type BackendEvent } from "@/lib/backend-events"
import {
    activeWorkspaceTab,
    isJobWorkspaceTab,
    createWorkspaceState,
    workspaceReducer,
    type WorkspaceAction,
    type WorkspaceTab,
    type WorkspaceTabGroup
} from "@/lib/workspace-tabs"
import {
    defaultPluginPlacements,
    panelPluginRegistry,
    type PanelPluginArea,
    type PanelPluginPlacement
} from "@/lib/panel"
import type { Size } from "motion-panels/react"
import type { SidecarStatus } from "./rpc"
import type { FileUploadState } from "@/hooks/use-file-upload"
import type {
    ConversionDetailState,
    ConversionDraft,
    ConversionLogState,
    ConversionReviewStep,
    ConversionStatusFilter,
    Theme
} from "./store-types"

function named<T extends Atom<unknown>>(value: T, name: string): T {
    value.debugLabel = name
    return value
}

// One explicit Provider store for the renderer. No token, file, or job is persisted.
export const store = createStore()
export const workspaceAtom = named(atom(createWorkspaceState()), "workspace")
export const workspaceActionAtom = named(
    atom(null, (get, set, action: WorkspaceAction) => {
        const next = workspaceReducer(get(workspaceAtom), action)
        set(workspaceAtom, next)
        // An already-selected secondary tab still needs to reveal a folded editor.
        if (
            action.type === "open" &&
            next.activeGroup === "secondary" &&
            next.groups.secondary.tabs.some((tab) => tab.id === action.tab.id)
        ) {
            set(secondaryCollapsedAtom, false)
        }
    }),
    "workspace.action"
)
export const tabItemsAtom = named(
    atom((get) => get(workspaceAtom).groups[get(workspaceAtom).activeGroup].tabs),
    "workspace.tabs"
)
export const activeTabAtom = named(
    atom(
        (get) => get(workspaceAtom).groups[get(workspaceAtom).activeGroup].activeId,
        (get, set, id: string) =>
            set(workspaceActionAtom, { type: "select", group: get(workspaceAtom).activeGroup, tabId: id })
    ),
    "workspace.activeTab"
)
export const activeWorkspaceTabAtom = named(
    atom((get) => activeWorkspaceTab(get(workspaceAtom))),
    "workspace.activeView"
)
export const sidebarWidthAtom = named(atom(180), "panels.sidebar.width")
export const inspectorWidthAtom = named(atom(200), "panels.inspector.width")
export const secondaryWidthAtom = named(atom<Size>("45%"), "panels.secondary.width")
export const dockHeightAtom = named(atom(210), "panels.dock.height")
export const sidebarCollapsedAtom = named(atom(false), "panels.sidebar.collapsed")
export const inspectorCollapsedAtom = named(atom(false), "panels.inspector.collapsed")
export const dockCollapsedAtom = named(atom(false), "panels.dock.collapsed")
export const secondaryCollapsedAtom = named(atom(false), "panels.secondary.collapsed")
export const titlebarPopoverOpenAtom = named(atom(false), "titlebar.menu.open")
export const panelCollapsedAtoms = {
    sidebar: sidebarCollapsedAtom,
    inspector: inspectorCollapsedAtom,
    dock: dockCollapsedAtom
} as const
export const pluginPlacementsAtom = named(atom<PanelPluginPlacement[]>(defaultPluginPlacements()), "panels.plugins")
export type PanelAction =
    | { type: "set-open"; area: PanelPluginArea; open: boolean }
    | { type: "toggle"; area: PanelPluginArea }
    | { type: "add" | "open"; id: string; area?: PanelPluginArea; index?: number }
    | { type: "close"; id: string }
    | { type: "remove"; id: string }
    | { type: "move"; id: string; area: PanelPluginArea; index?: number }
    | { type: "set-expanded"; area: PanelPluginArea; ids: readonly string[] }

// Position is an index within the destination area; omitted means append.
// open adds a removed plugin at its default area. add is idempotent for existing placements.
export const panelActionAtom = named(
    atom(null, (get, set, action: PanelAction) => {
        if (action.type === "set-open" || action.type === "toggle") {
            const collapsed = panelCollapsedAtoms[action.area]
            set(collapsed, action.type === "toggle" ? !get(collapsed) : !action.open)
            return
        }
        const placements = get(pluginPlacementsAtom)
        if (action.type === "set-expanded") {
            set(
                pluginPlacementsAtom,
                placements.map((placement) =>
                    placement.area === action.area
                        ? { ...placement, expanded: action.ids.includes(placement.id) }
                        : placement
                )
            )
            return
        }
        const existing = placements.find((placement) => placement.id === action.id)
        if (action.type === "close" || action.type === "remove") {
            if (!existing) return
            set(
                pluginPlacementsAtom,
                action.type === "remove"
                    ? placements.filter((placement) => placement.id !== action.id)
                    : placements.map((placement) =>
                          placement.id === action.id ? { ...placement, expanded: false } : placement
                      )
            )
            return
        }
        if (action.type === "open" && existing) {
            set(panelCollapsedAtoms[existing.area], false)
            set(
                pluginPlacementsAtom,
                placements.map((placement) =>
                    placement.id === action.id ? { ...placement, expanded: true } : placement
                )
            )
            return
        }
        if (action.type === "add" && existing) return
        const definition = panelPluginRegistry.getPlugin(action.id)
        if (!definition || (action.type === "move" && !existing)) return
        const area = action.area ?? definition.area
        const placement: PanelPluginPlacement = existing
            ? { ...existing, area }
            : { id: action.id, area, expanded: true }
        const others = placements.filter((entry) => entry.id !== action.id)
        const destination = others.filter((entry) => entry.area === area)
        const requested = action.index ?? destination.length
        const index = Number.isFinite(requested)
            ? Math.max(0, Math.min(Math.trunc(requested), destination.length))
            : destination.length
        const before = destination[index]
        const insertion = before ? others.indexOf(before) : others.length
        set(pluginPlacementsAtom, [...others.slice(0, insertion), placement, ...others.slice(insertion)])
        set(panelCollapsedAtoms[area], false)
    }),
    "panels.action"
)
export const eventsOpenAtom = named(
    atom((get) => {
        const placement = get(pluginPlacementsAtom).find((plugin) => plugin.id === "dock-events")
        return !!placement?.expanded && !get(panelCollapsedAtoms[placement.area])
    }),
    "panels.events.visible"
)
export const showEventsAtom = named(
    atom(null, (_get, set) => {
        set(panelActionAtom, { type: "open", id: "dock-events" })
    }),
    "panels.events.show"
)

export const requestTokenAtom = named(atom(""), "auth.requestToken")
export const tokenDraftAtom = named(atom(""), "auth.tokenDraft")
export const conversionSessionAtom = named(atom(0), "jobs.session")
export const lastEndpointAtom = named(atom<string | null>(null), "backend.lastEndpoint")
export const backendControllerAtom = named(
    atom(
        () =>
            new BackendPolling(async () => {
                const { getSidecarStatus } = await import("@/mainview/backend")
                return getSidecarStatus()
            })
    ),
    "backend.controller"
)
const initialBackend: BackendPollingSnapshot = {
    backend: { state: "starting", url: null, error: null, authRequired: null },
    isAutoEnabled: true,
    isActive: false,
    isChecking: false,
    lastCheckedAt: null,
    responseTimeMs: null
}
export const backendSnapshotAtom = named(atom<BackendPollingSnapshot>(initialBackend), "backend.snapshot")
export const backendAtom = named(
    atom((get) => get(backendSnapshotAtom).backend),
    "backend.status"
)
export const backendEventsAtom = named(atom<BackendEvent[]>([]), "backend.events")
const previousBackendAtom = named(atom<SidecarStatus | null>(null), "backend.previousStatus")
const backendEventSequenceAtom = named(atom(0), "backend.events.sequence")
export const recordBackendEventAtom = named(
    atom(null, (get, set, status: SidecarStatus) => {
        const description = describeBackendEvent(get(previousBackendAtom), status)
        set(previousBackendAtom, status)
        if (!description) return
        const id = get(backendEventSequenceAtom) + 1
        set(backendEventSequenceAtom, id)
        set(backendEventsAtom, (events) => [{ ...description, id, timestamp: Date.now() }, ...events].slice(0, 50))
    }),
    "backend.events.record"
)
export const clearBackendEventsAtom = named(
    atom(null, (_get, set) => set(backendEventsAtom, [])),
    "backend.events.clear"
)

export const conversionEndpointAtom = named(
    atom((get) => get(backendAtom).url ?? get(lastEndpointAtom)),
    "jobs.endpoint"
)
export const conversionClientAtom = named(
    atom((get) => new ConversionClient(get(conversionEndpointAtom), get(requestTokenAtom))),
    "jobs.client"
)
export const conversionSnapshotSourceAtom = named(
    atom<{ client: ConversionClient | null; snapshot: ConversionSnapshot }>({
        client: null,
        snapshot: { jobs: [], isLoading: false, isSubmitting: false, error: null }
    }),
    "jobs.snapshotSource"
)
export const conversionSnapshotAtom = named(
    atom((get) => {
        const client = get(conversionClientAtom)
        const source = get(conversionSnapshotSourceAtom)
        return source.client === client ? source.snapshot : client.getSnapshot()
    }),
    "jobs.snapshot"
)

export const inspectedJobIdAtom = named(atom<string | null>(null), "jobs.inspectedId")
export const selectedJobAtom = named(
    atom((get) => {
        const id = get(activeWorkspaceTabAtom)?.jobId ?? get(inspectedJobIdAtom)
        return get(conversionSnapshotAtom).jobs.find((job) => job.id === id) ?? null
    }),
    "jobs.inspected"
)

export const themeAtom = named(atom<Theme>("system"), "appearance.theme")
export const systemDarkAtom = named(atom(false), "appearance.systemDark")
export const resolvedThemeAtom = named(
    atom((get) => {
        const theme = get(themeAtom)
        return theme === "system" ? (get(systemDarkAtom) ? "dark" : "light") : theme
    }),
    "appearance.resolvedTheme"
)

export const jobsCreatingAtom = named(atom<boolean | null>(null), "jobs.view.creating")
export const jobsSelectedIdAtom = named(atom<string | null>(null), "jobs.view.selectedId")
export const jobsQueryAtom = named(atom(""), "jobs.view.query")
export const jobsStatusFilterAtom = named(atom<ConversionStatusFilter>("all"), "jobs.view.statusFilter")
export const jobsRefreshingAtom = named(atom(false), "jobs.view.refreshing")
export const jobsLocalErrorAtom = named(atom<string | null>(null), "jobs.view.error")
export const jobsAnnouncementAtom = named(atom(""), "jobs.view.announcement")
export const initialConversionDraft: ConversionDraft = {
    name: "",
    description: "",
    source_format: "",
    output_format: "corpus",
    category: ""
}
export const conversionDraftAtom = named(atom<ConversionDraft>(initialConversionDraft), "conversion.form.draft")
export const conversionStepAtom = named(atom<ConversionReviewStep>(0), "conversion.form.step")
export const conversionFormErrorAtom = named(atom<string | null>(null), "conversion.form.error")
export const conversionPendingAtom = named(atom(false), "conversion.form.pending")
export const fileUploadAtom = named(
    atom<FileUploadState>({ files: [], isDragging: false, errors: [] }),
    "conversion.upload"
)
export const resetConversionFormAtom = named(
    atom(null, (get, set) => {
        for (const entry of get(fileUploadAtom).files) {
            if (entry.preview?.startsWith("blob:")) URL.revokeObjectURL(entry.preview)
        }
        set(fileUploadAtom, { files: [], isDragging: false, errors: [] })
        set(conversionDraftAtom, { ...initialConversionDraft })
        set(conversionStepAtom, 0)
        set(conversionFormErrorAtom, null)
        set(conversionPendingAtom, false)
    }),
    "conversion.form.reset"
)

// Central, stable atom families retain per-job state across tab moves and folds.
// Fields subscribe independently; editing one log viewer does not reset another.
const detailStatesAtom = named(atom<Record<string, ConversionDetailState>>({}), "jobs.details")
const logStatesAtom = named(atom<Record<string, ConversionLogState>>({}), "jobs.logs")
function fieldAtom<T, K extends keyof T>(
    records: PrimitiveAtom<Record<string, T>>,
    key: string,
    field: K,
    initial: T,
    label: string
) {
    return named(
        atom(
            (get) => (get(records)[key] ?? initial)[field],
            (get, set, update: T[K] | ((previous: T[K]) => T[K])) => {
                const recordsValue = get(records)
                const current = recordsValue[key] ?? initial
                const value =
                    typeof update === "function" ? (update as (previous: T[K]) => T[K])(current[field]) : update
                set(records, { ...recordsValue, [key]: { ...current, [field]: value } })
            }
        ),
        label
    )
}
function createDetailAtoms(key: string) {
    const initial: ConversionDetailState = { stage: null, downloading: false, downloadError: null }
    return {
        stage: fieldAtom(detailStatesAtom, key, "stage", initial, `job.${key}.stage`),
        downloading: fieldAtom(detailStatesAtom, key, "downloading", initial, `job.${key}.downloading`),
        downloadError: fieldAtom(detailStatesAtom, key, "downloadError", initial, `job.${key}.downloadError`)
    }
}
function createLogAtoms(key: string) {
    const initial: ConversionLogState = {
        search: "",
        selectedLevels: ["debug", "info", "warning", "error", "unclassified"],
        copyState: "idle",
        copyError: null,
        copiedText: null
    }
    return {
        search: fieldAtom(logStatesAtom, key, "search", initial, `logs.${key}.search`),
        selectedLevels: fieldAtom(logStatesAtom, key, "selectedLevels", initial, `logs.${key}.levels`),
        copyState: fieldAtom(logStatesAtom, key, "copyState", initial, `logs.${key}.copyState`),
        copyError: fieldAtom(logStatesAtom, key, "copyError", initial, `logs.${key}.copyError`),
        copiedText: fieldAtom(logStatesAtom, key, "copiedText", initial, `logs.${key}.copiedText`)
    }
}
const detailAtoms = new Map<string, ReturnType<typeof createDetailAtoms>>()
const logAtoms = new Map<string, ReturnType<typeof createLogAtoms>>()
export function conversionDetailAtomsFor(key: string): ReturnType<typeof createDetailAtoms> {
    let atoms = detailAtoms.get(key)
    if (!atoms) {
        atoms = createDetailAtoms(key)
        detailAtoms.set(key, atoms)
    }
    return atoms
}
export function conversionLogAtomsFor(key: string): ReturnType<typeof createLogAtoms> {
    let atoms = logAtoms.get(key)
    if (!atoms) {
        atoms = createLogAtoms(key)
        logAtoms.set(key, atoms)
    }
    return atoms
}
function withoutJobTabs(group: WorkspaceTabGroup): WorkspaceTabGroup {
    const retain = (tab: WorkspaceTab) => !isJobWorkspaceTab(tab)
    const tabs = group.tabs.filter(retain)
    if (tabs.length === group.tabs.length) return group
    const activeIndex = group.tabs.findIndex((tab) => tab.id === group.activeId)
    const activeId = tabs.some((tab) => tab.id === group.activeId)
        ? group.activeId
        : (group.tabs.slice(activeIndex + 1).find(retain)?.id ??
          group.tabs.slice(0, activeIndex).reverse().find(retain)?.id ??
          null)
    return { tabs, activeId }
}

export const resetConversionViewsAtom = named(
    atom(null, (get, set) => {
        // Job titles and IDs are identity-bound metadata, even after snapshots clear.
        const workspace = get(workspaceAtom)
        const primary = withoutJobTabs(workspace.groups.primary)
        const secondary = withoutJobTabs(workspace.groups.secondary)
        if (primary !== workspace.groups.primary || secondary !== workspace.groups.secondary) {
            set(workspaceAtom, { ...workspace, groups: { primary, secondary } })
        }
        set(jobsCreatingAtom, null)
        set(jobsSelectedIdAtom, null)
        set(inspectedJobIdAtom, null)
        set(jobsQueryAtom, "")
        set(jobsStatusFilterAtom, "all")
        set(jobsRefreshingAtom, false)
        set(jobsLocalErrorAtom, null)
        set(jobsAnnouncementAtom, "")
        set(detailStatesAtom, {})
        set(logStatesAtom, {})
        set(resetConversionFormAtom)
        set(conversionSessionAtom, (session) => session + 1)
    }),
    "jobs.views.reset"
)
export const applyRequestTokenAtom = named(
    atom(null, (get, set, token: string) => {
        const normalized = token.trim().replace(/^Bearer\s+/i, "")
        if (normalized !== get(requestTokenAtom)) {
            set(requestTokenAtom, normalized)
            set(resetConversionViewsAtom)
        }
        set(tokenDraftAtom, "")
    }),
    "auth.applyToken"
)
export const resetWorkspaceAtom = named(
    atom(null, (_get, set) => {
        set(workspaceAtom, createWorkspaceState())
        set(sidebarWidthAtom, 256)
        set(inspectorWidthAtom, 256)
        set(secondaryWidthAtom, "45%")
        set(dockHeightAtom, 210)
        set(sidebarCollapsedAtom, false)
        set(inspectorCollapsedAtom, false)
        set(secondaryCollapsedAtom, false)
        set(dockCollapsedAtom, true)
        set(pluginPlacementsAtom, defaultPluginPlacements())
        set(titlebarPopoverOpenAtom, false)
    }),
    "workspace.reset"
)
