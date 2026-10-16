import { ExploreTab } from "@/mainview/views/explore-tab"
import { HomeTab } from "@/mainview/views/home-tab"
import { JobTab } from "@/mainview/views/jobs-tab"
import { SettingsTab } from "@/mainview/views/settings-tab"
import { BookSearch, House, type LucideIcon } from "lucide-react"
import type { WorkspaceTab } from "@/lib/workspace-tabs"

export type TabID = "tab:home" | "tab:explorer" | "jobs" | "settings"
export type TTabItem = { id: TabID; label: string; icon: LucideIcon; content: WorkspaceTab["view"] }

export const destinations: TTabItem[] = [
    { id: "tab:home", label: "Home", content: HomeTab, icon: House },
    { id: "tab:explorer", label: "Explorer", content: ExploreTab, icon: BookSearch }
]

export function navigationTab(id: TabID): WorkspaceTab {
    switch (id) {
        case "tab:home":
            return { id, title: "Home", view: HomeTab, pinned: true }
        case "tab:explorer":
            return { id, title: "Explorer", view: ExploreTab, pinned: true }
        case "jobs":
            return { id, title: "Conversion jobs", view: JobTab, pinned: false }
        case "settings":
            return { id, title: "Settings", view: SettingsTab, pinned: false }
    }
}
