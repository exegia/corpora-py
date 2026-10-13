import { HomeTab } from "@/mainview/views/home-tab"
import { UUID } from "crypto"
import { Compass, FolderSyncIcon, Home, type icons } from "lucide-react"
import React, { FC } from "react"

export const navigation: TTabItem[] = [
    { id: "dashboard", label: "Home", icon: "House", content: HomeTab },
    { id: "jobs", label: "Jobs", icon: "FolderSync", content: Job },
    { value: "explorer", label: "Explorer", icon: "Compass" }
]

export type TNavigationItem = (typeof navigation)[number]
export type TabID = "dashboard" | "jobs" | "explorer" | UUID
export type TabItemBase<ID extends TabID> = {
  readonly id: ID
  label: string
  content: FC
  icon: keyof typeof icons
}
export type TTabItem<ID extends TabID = TabID, Base extends TabItemBase<ID> = TabItemBase<ID>> = ID extends UUID ? Base & {
    closable: Readonly<true>
} : Base
