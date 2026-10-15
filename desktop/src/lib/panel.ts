import type { ComponentType, ReactNode } from "react"

export const panelAreas = ["sidebar", "inspector", "dock"] as const
export type PanelPluginArea = (typeof panelAreas)[number]

export interface IPanelPluginProps {
    readonly id: string
    name: string
    area: PanelPluginArea
    children?: ReactNode
}

/** Definition area is only the default; placement and expansion live in Jotai. */
export interface IPanelPlugin {
    readonly id: string
    readonly area: PanelPluginArea
    readonly name: string
    readonly component: ComponentType<IPanelPluginProps>
}

export class PanelPluginRegistry {
    private definitions = new Map<string, IPanelPlugin>()

    // Re-registering a definition replaces its renderer (including during Vite HMR), never its placement.
    registerPlugin(plugin: IPanelPlugin) {
        if (!plugin.id.trim()) throw new Error("A panel plugin needs a stable ID")
        this.definitions.set(plugin.id, Object.freeze({ ...plugin }))
    }

    getPlugin(id: string): IPanelPlugin | undefined {
        return this.definitions.get(id)
    }

    get plugins(): readonly IPanelPlugin[] {
        return Array.from(this.definitions.values())
    }
}

// Register definitions before mounting the workspace. Removing a placement does not unregister a definition.
export const panelPluginRegistry = new PanelPluginRegistry()
export interface PanelPluginPlacement {
    id: string
    area: PanelPluginArea
    expanded: boolean
}
export function defaultPluginPlacements(): PanelPluginPlacement[] {
    return [
        { id: "sidebar-navigation", area: "sidebar", expanded: true },
        { id: "sidebar-jobs", area: "sidebar", expanded: true },
        { id: "inspector-job", area: "inspector", expanded: true },
        { id: "inspector-backend", area: "inspector", expanded: true },
        { id: "dock-events", area: "dock", expanded: true },
        { id: "dock-logs", area: "dock", expanded: false }
    ]
}
