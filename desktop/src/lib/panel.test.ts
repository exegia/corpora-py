import { describe, expect, test } from "bun:test"
import { createStore } from "jotai"
import "../mainview/panel-plugins"
import { PanelPluginRegistry, panelPluginRegistry, type PanelPluginArea } from "./panel"
import * as atoms from "../shared/store"

const areaPlugins = (store: ReturnType<typeof createStore>, area: PanelPluginArea) =>
    store.get(atoms.pluginPlacementsAtom).filter((placement) => placement.area === area)

const ids = (store: ReturnType<typeof createStore>, area: PanelPluginArea) =>
    areaPlugins(store, area).map((placement) => placement.id)

describe("panel plugin definitions and placements", () => {
    test("definitions have stable IDs, and replacing a renderer does not mutate placement", () => {
        const registry = new PanelPluginRegistry()
        const component = () => null
        registry.registerPlugin({ id: "tool", name: "Tool", area: "sidebar", component })
        expect(registry.getPlugin("tool")?.component).toBe(component)
        expect(Object.isFrozen(registry.getPlugin("tool"))).toBe(true)
        registry.registerPlugin({ id: "tool", name: "Renamed tool", area: "dock", component })
        expect(registry.plugins).toHaveLength(1)
        expect(registry.getPlugin("missing")).toBeUndefined()
        expect(() => registry.registerPlugin({ id: " ", name: "Invalid", area: "dock", component })).toThrow()
    })

    test("expands multiple sections independently and opening one reveals only its panel", () => {
        const store = createStore()
        store.set(atoms.inspectorCollapsedAtom, true)
        store.set(atoms.dockCollapsedAtom, true)
        store.set(atoms.panelActionAtom, { type: "open", id: "dock-logs" })
        expect(areaPlugins(store, "dock").every((placement) => placement.expanded)).toBe(true)
        expect(store.get(atoms.dockCollapsedAtom)).toBe(false)
        expect(store.get(atoms.inspectorCollapsedAtom)).toBe(true)
        store.set(atoms.panelActionAtom, { type: "close", id: "dock-events" })
        expect(areaPlugins(store, "dock")).toEqual([
            { id: "dock-events", area: "dock", expanded: false },
            { id: "dock-logs", area: "dock", expanded: true }
        ])
        store.set(atoms.panelActionAtom, { type: "set-expanded", area: "sidebar", ids: ["sidebar-jobs", "dock-logs"] })
        expect(areaPlugins(store, "sidebar").map((placement) => placement.expanded)).toEqual([false, true])
        expect(areaPlugins(store, "dock")[1].expanded).toBe(true)
    })

    test("moves preserve identity and expansion, reveal the destination and respect destination order", () => {
        const store = createStore()
        store.set(atoms.inspectorCollapsedAtom, true)
        store.set(atoms.panelActionAtom, { type: "move", id: "dock-logs", area: "inspector", index: 1 })
        expect(ids(store, "inspector")).toEqual(["inspector-job", "dock-logs", "inspector-backend"])
        expect(ids(store, "dock")).toEqual(["dock-events"])
        expect(store.get(atoms.inspectorCollapsedAtom)).toBe(false)
        expect(areaPlugins(store, "inspector")[1]).toEqual({ id: "dock-logs", area: "inspector", expanded: false })
        store.set(atoms.panelActionAtom, { type: "open", id: "dock-logs" })
        expect(areaPlugins(store, "inspector")[1].expanded).toBe(true)
        expect(ids(store, "dock")).toEqual(["dock-events"])
        store.set(atoms.panelActionAtom, { type: "move", id: "dock-logs", area: "sidebar", index: -10 })
        expect(ids(store, "sidebar")).toEqual(["dock-logs", "sidebar-navigation", "sidebar-jobs"])
        store.set(atoms.panelActionAtom, { type: "move", id: "dock-logs", area: "sidebar", index: 999 })
        expect(ids(store, "sidebar")).toEqual(["sidebar-navigation", "sidebar-jobs", "dock-logs"])
        store.set(atoms.panelActionAtom, { type: "move", id: "sidebar-jobs", area: "sidebar", index: 0 })
        expect(ids(store, "sidebar")).toEqual(["sidebar-jobs", "sidebar-navigation", "dock-logs"])
        const placements = store.get(atoms.pluginPlacementsAtom)
        expect(new Set(placements.map((placement) => placement.id)).size).toBe(placements.length)
    })

    test("close retains the header; remove retains registration; open re-adds at the default area", () => {
        const store = createStore()
        const definition = panelPluginRegistry.getPlugin("dock-logs")
        store.set(atoms.panelActionAtom, { type: "close", id: "dock-logs" })
        expect(ids(store, "dock")).toContain("dock-logs")
        store.set(atoms.panelActionAtom, { type: "remove", id: "dock-logs" })
        expect(ids(store, "dock")).not.toContain("dock-logs")
        expect(panelPluginRegistry.getPlugin("dock-logs")).toBe(definition)
        store.set(atoms.panelActionAtom, { type: "add", id: "dock-logs", area: "sidebar", index: 0 })
        expect(ids(store, "sidebar")[0]).toBe("dock-logs")
        store.set(atoms.panelActionAtom, { type: "add", id: "dock-logs", area: "dock" })
        expect(ids(store, "dock")).not.toContain("dock-logs")
        store.set(atoms.panelActionAtom, { type: "remove", id: "dock-logs" })
        store.set(atoms.dockCollapsedAtom, true)
        store.set(atoms.panelActionAtom, { type: "open", id: "dock-logs" })
        expect(areaPlugins(store, "dock")[areaPlugins(store, "dock").length - 1]).toEqual({
            id: "dock-logs",
            area: "dock",
            expanded: true
        })
        expect(store.get(atoms.dockCollapsedAtom)).toBe(false)
    })

    test("unknown definitions and missing moves cannot create phantom placements", () => {
        const store = createStore()
        store.set(atoms.panelActionAtom, { type: "remove", id: "dock-logs" })
        const previous = store.get(atoms.pluginPlacementsAtom)
        for (const type of ["open", "add", "move", "close", "remove"] as const) {
            store.set(
                atoms.panelActionAtom,
                type === "move" ? { type, id: "unknown", area: "sidebar" } : { type, id: "unknown" }
            )
            expect(store.get(atoms.pluginPlacementsAtom)).toBe(previous)
        }
        store.set(atoms.panelActionAtom, { type: "move", id: "dock-logs", area: "sidebar" })
        expect(store.get(atoms.pluginPlacementsAtom)).toBe(previous)
    })

    test("folding every panel retains resized extents and exact plugin arrangement", () => {
        const store = createStore()
        store.set(atoms.sidebarWidthAtom, 270)
        store.set(atoms.inspectorWidthAtom, 310)
        store.set(atoms.dockHeightAtom, 290)
        store.set(atoms.panelActionAtom, { type: "move", id: "dock-logs", area: "inspector", index: 0 })
        const previous = store.get(atoms.pluginPlacementsAtom)
        for (const area of ["sidebar", "inspector", "dock"] as const) {
            store.set(atoms.panelActionAtom, { type: "set-open", area, open: false })
            expect(store.get(atoms.panelCollapsedAtoms[area])).toBe(true)
            store.set(atoms.panelActionAtom, { type: "toggle", area })
            expect(store.get(atoms.panelCollapsedAtoms[area])).toBe(false)
        }
        expect(store.get(atoms.pluginPlacementsAtom)).toBe(previous)
        expect(store.get(atoms.sidebarWidthAtom)).toBe(270)
        expect(store.get(atoms.inspectorWidthAtom)).toBe(310)
        expect(store.get(atoms.dockHeightAtom)).toBe(290)
    })

    test("keyed plugin controls survive moves and removal without affecting jobs, controllers, or another store", () => {
        const store = createStore()
        const other = createStore()
        const controls = atoms.conversionLogAtomsFor("0:dock-logs:a")
        const detail = atoms.conversionLogAtomsFor("0:detail:a")
        store.set(controls.search, "retained search")
        store.set(controls.selectedLevels, ["error"])
        store.set(detail.search, "detail search")
        const client = store.get(atoms.conversionClientAtom)
        const backend = store.get(atoms.backendControllerAtom)
        const snapshot = store.get(atoms.conversionSnapshotAtom)
        const workspace = store.get(atoms.workspaceAtom)
        const otherPlacements = other.get(atoms.pluginPlacementsAtom)
        for (const action of [
            { type: "close", id: "dock-logs" },
            { type: "move", id: "dock-logs", area: "sidebar" },
            { type: "remove", id: "dock-logs" },
            { type: "open", id: "dock-logs" }
        ] as const)
            store.set(atoms.panelActionAtom, action)
        expect(atoms.conversionLogAtomsFor("0:dock-logs:a")).toBe(controls)
        expect(store.get(controls.search)).toBe("retained search")
        expect(store.get(controls.selectedLevels)).toEqual(["error"])
        expect(store.get(detail.search)).toBe("detail search")
        expect(store.get(atoms.conversionSnapshotAtom)).toBe(snapshot)
        expect(store.get(atoms.conversionClientAtom)).toBe(client)
        expect(store.get(atoms.backendControllerAtom)).toBe(backend)
        expect(store.get(atoms.workspaceAtom)).toBe(workspace)
        expect(other.get(controls.search)).toBe("")
        expect(other.get(atoms.pluginPlacementsAtom)).toBe(otherPlacements)
        expect(store.get(atoms.conversionLogAtomsFor("0:dock-logs:b").search)).toBe("")
    })
})
