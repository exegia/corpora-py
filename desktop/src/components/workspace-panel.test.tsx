import { describe, expect, test } from "bun:test"
import { createStore, Provider } from "jotai"
import { renderToStaticMarkup } from "react-dom/server"
import "../mainview/panel-plugins"
import { WorkspacePanel } from "./workspace-panel"
import {
    conversionLogAtomsFor,
    conversionClientAtom,
    conversionSnapshotSourceAtom,
    inspectedJobIdAtom,
    panelActionAtom
} from "../shared/store"
import type { ConversionJob } from "../shared/conversion"
import type { PanelPluginArea } from "../lib/panel"

function render(store: ReturnType<typeof createStore>, area: PanelPluginArea) {
    return renderToStaticMarkup(
        <Provider store={store}>
            <WorkspacePanel area={area} />
        </Provider>
    )
}

describe("workspace plugin hosts", () => {
    test("renders two independently expanded sections and retains a folded section's header", () => {
        const store = createStore()
        const before = render(store, "sidebar")
        expect(before.match(/aria-expanded="true"/g)).toHaveLength(2)
        expect(before).toContain('aria-label="Navigation options"')
        expect(before).toContain('aria-label="Recent jobs options"')
        store.set(panelActionAtom, { type: "close", id: "sidebar-navigation" })
        const folded = render(store, "sidebar")
        expect(folded.match(/aria-expanded="true"/g)).toHaveLength(1)
        expect(folded).toContain('data-plugin-id="sidebar-navigation"')
        expect(folded).toContain('data-plugin-id="sidebar-jobs"')
    })

    test("moves actual log controls between hosts without resetting keyed filters", () => {
        const store = createStore()
        const job: ConversionJob = {
            id: "a",
            name: "Source",
            display_name: null,
            source_format: "plain",
            output_format: "corpus",
            status: "running",
            created_at: 1000,
            started_at: 1001,
            finished_at: null,
            error: null,
            logs: [],
            last_log: null,
            events: [],
            steps: [],
            validation: null,
            result_filename: "a.corpus",
            download_ready: false
        }
        store.set(conversionSnapshotSourceAtom, {
            client: store.get(conversionClientAtom),
            snapshot: { jobs: [job], isLoading: false, isSubmitting: false, error: null }
        })
        store.set(inspectedJobIdAtom, "a")
        store.set(panelActionAtom, { type: "open", id: "dock-logs" })
        store.set(conversionLogAtomsFor("0:dock-logs:a").search, "retained filter")
        expect(render(store, "dock")).toContain('value="retained filter"')
        store.set(panelActionAtom, { type: "move", id: "dock-logs", area: "inspector", index: 0 })
        expect(render(store, "dock")).not.toContain('data-plugin-id="dock-logs"')
        const moved = render(store, "inspector")
        expect(moved).toContain('data-plugin-id="dock-logs"')
        expect(moved).toContain('value="retained filter"')
        store.set(panelActionAtom, { type: "remove", id: "dock-logs" })
        expect(render(store, "inspector")).not.toContain('data-plugin-id="dock-logs"')
        store.set(panelActionAtom, { type: "open", id: "dock-logs", area: "sidebar" })
        expect(render(store, "sidebar")).toContain('value="retained filter"')
    })
})
