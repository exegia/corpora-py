import { describe, expect, test } from "bun:test"
import { createStore, Provider } from "jotai"
import { renderToStaticMarkup } from "react-dom/server"
import { TitleBar } from "../title-bar"
import { TabLayout } from "./tab-layout"
import { Tabs, TabsList, TabsTrigger } from "../ui/tabs"
import { createWorkspaceState, workspaceReducer } from "../../lib/workspace-tabs"
import { navigationTab } from "../../shared/navigation"
import * as atoms from "../../shared/store"

const noOp = () => {}

function editor(workspace = createWorkspaceState()) {
    return renderToStaticMarkup(
        <TabLayout
            group="primary"
            workspace={workspace}
            dispatch={noOp}
            renderTab={(tab) => <p>{tab.title} content</p>}
        />
    )
}

describe("top navigation and editor tabs", () => {
    test("includes secondary tabs in the titlebar and leaves a draggable spacer", () => {
        const store = createStore()
        store.set(atoms.workspaceActionAtom, { type: "open", tab: navigationTab("settings"), target: "secondary" })
        const markup = renderToStaticMarkup(<Provider store={store}><TitleBar onOpenSettings={noOp} /></Provider>)
        expect(markup).toContain('data-workspace-tab-id="settings"')
        expect(markup).toContain('data-titlebar-drag-space="true"')
        expect(markup.match(/aria-label="Close Settings"/g)).toHaveLength(1)
    })

    test("sidebar collapses to a 56px rail and restores its remembered width", () => {
        const store = createStore()
        store.set(atoms.sidebarWidthAtom, 320)
        store.set(atoms.panelActionAtom, { type: "set-open", area: "sidebar", open: false })
        expect(store.get(atoms.sidebarPanelWidthAtom)).toBe(56)
        expect(store.get(atoms.sidebarWidthAtom)).toBe(320)
        store.set(atoms.panelActionAtom, { type: "toggle", area: "sidebar" })
        expect(store.get(atoms.sidebarPanelWidthAtom)).toBe(320)
        store.set(atoms.sidebarPanelWidthAtom, 56)
        expect(store.get(atoms.sidebarCollapsedAtom)).toBe(true)
        store.set(atoms.sidebarPanelWidthAtom, 280)
        expect(store.get(atoms.sidebarCollapsedAtom)).toBe(false)
        expect(store.get(atoms.sidebarPanelWidthAtom)).toBe(280)
    })

    test("the inspector starts collapsed and layout reset keeps the startup default", () => {
        const store = createStore()
        expect(store.get(atoms.inspectorCollapsedAtom)).toBe(true)
        store.set(atoms.panelActionAtom, { type: "set-open", area: "inspector", open: true })
        expect(store.get(atoms.inspectorCollapsedAtom)).toBe(false)
        store.set(atoms.resetWorkspaceAtom)
        expect(store.get(atoms.inspectorCollapsedAtom)).toBe(true)
    })

    test("always offers Home and Explorer in top navigation without duplicating editor triggers", () => {
        const store = createStore()
        const titlebar = renderToStaticMarkup(
            <Provider store={store}>
                <TitleBar onOpenSettings={noOp} />
            </Provider>
        )
        expect(titlebar).toContain('data-top-navigation="tab:home"')
        expect(titlebar).toContain('data-top-navigation="tab:explorer"')
        const home = editor()
        expect(home).toContain("Home content")
        expect(home).not.toContain('data-workspace-tab-id="tab:home"')
        const explorer = workspaceReducer(createWorkspaceState(), {
            type: "open",
            tab: navigationTab("tab:explorer"),
            target: "secondary"
        })
        expect(explorer.activeGroup).toBe("primary")
        expect(explorer.groups.secondary.tabs).toEqual([])
        const content = editor(explorer)
        expect(content).toContain("Explorer content")
        expect(content).not.toContain('data-workspace-tab-id="tab:explorer"')
    })

    test("retains real close buttons beside tab triggers instead of nesting buttons", async () => {
        const workspace = workspaceReducer(createWorkspaceState(), { type: "open", tab: navigationTab("settings") })
        const store = createStore()
        store.set(atoms.workspaceAtom, workspace)
        const markup = renderToStaticMarkup(<Provider store={store}><TitleBar onOpenSettings={noOp} /></Provider>)
        expect(editor(workspace)).not.toContain('data-workspace-tab-id=')
        expect(editor(workspace)).not.toContain('tabs menu')
        expect(markup).toContain('aria-label="Close Settings"')
        expect(markup).toContain('data-workspace-tab-id="settings"')
        let nestedButtons = 0
        await new HTMLRewriter()
            .on("button button", {
                element() {
                    nestedButtons++
                }
            })
            .transform(new Response(markup))
            .text()
        expect(nestedButtons).toBe(0)
        expect(markup).not.toContain('data-workspace-tab-id="tab:home"')
        expect(markup).toContain('data-liquid-glass="material"')
        let nestedLabels = 0
        await new HTMLRewriter().on("label button", { element() { nestedLabels++ } }).transform(new Response(markup)).text()
        expect(nestedLabels).toBe(0)
    })

    test("keeps top-level destinations immovable and restores fixed widths with an empty secondary", () => {
        const store = createStore()
        store.set(atoms.workspaceActionAtom, { type: "open", tab: navigationTab("tab:explorer"), target: "secondary" })
        const workspace = store.get(atoms.workspaceAtom)
        for (const action of [
            { type: "close", group: "primary", tabId: "tab:explorer" },
            { type: "move", group: "primary", tabId: "tab:explorer", target: "secondary" }
        ] as const)
            store.set(atoms.workspaceActionAtom, action)
        expect(store.get(atoms.workspaceAtom)).toBe(workspace)
        store.set(atoms.sidebarWidthAtom, 320)
        store.set(atoms.inspectorWidthAtom, 380)
        store.set(atoms.resetWorkspaceAtom)
        expect(store.get(atoms.sidebarWidthAtom)).toBe(atoms.PANEL_DEFAULT_WIDTH)
        expect(store.get(atoms.inspectorWidthAtom)).toBe(atoms.PANEL_DEFAULT_WIDTH)
        expect(store.get(atoms.secondaryCollapsedAtom)).toBe(true)
        expect(store.get(atoms.workspaceAtom).groups.secondary.tabs).toEqual([])
    })
})

describe("selected tab materials", () => {
    test("glass keeps the real material within the selection indicator without fixed geometry", () => {
        const markup = renderToStaticMarkup(
            <Tabs value="one">
                <TabsList variant="glass">
                    <TabsTrigger value="one">One</TabsTrigger>
                    <TabsTrigger value="two">Two</TabsTrigger>
                </TabsList>
            </Tabs>
        )
        expect(markup).toContain('data-slot="tab-indicator"')
        expect(markup).toContain('data-liquid-glass="material"')
        expect(markup).toContain('aria-hidden="true"')
        expect(markup).toContain('role="tablist"')
        expect(markup).toContain('role="tab"')
        expect(markup).not.toContain("width:300px")
        expect(markup).not.toContain("bg-black")
    })
})
