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
            onRevealGroup={noOp}
            onNewConversion={noOp}
        />
    )
}

describe("top navigation and editor tabs", () => {
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
        const markup = editor(workspace)
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
        expect(store.get(atoms.sidebarWidthAtom)).toBe(470)
        expect(store.get(atoms.inspectorWidthAtom)).toBe(470)
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
