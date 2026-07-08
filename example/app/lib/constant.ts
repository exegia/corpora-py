import type { ComponentType, FC, SVGProps } from "react"
import { Uploading, MessagingApp, OnlineChat, SyncFiles, Searching } from "undraw-react"
import { BubblesIcon, ListIcon, LucideHome, FileSpreadsheet, LucideUploadCloud } from "lucide-react"
import type { UndrawSVGProps } from "undraw-react/dist/esm/types"

export const NAV = [
  { to: "/", label: "Home", icon: LucideHome },
  { to: "/corpus/upload", label: "Upload", icon: LucideUploadCloud },
  { to: "/corpus/convert", label: "Convert", icon: FileSpreadsheet },
  { to: "/chat", label: "Chat", icon: BubblesIcon }
]

type MenuItem = {
  description: string
  illustration?: ComponentType<UndrawSVGProps>
  label: string
  icon?: FC<UndrawSVGProps>
  to: string
}

export const MENU_ITEMS: MenuItem[] = [
  {
    label: "Home",
    description: "Start with the Corpora API tools.",
    icon: LucideHome,
    to: "/"
  },
  {
    label: "Convert",
    description: "Turn a source document into a Text-Fabric dataset.",
    illustration: SyncFiles,
    icon: LucideUploadCloud,
    to: "/corpus/convert"
  },
  {
    label: "Explore",
    description: "View and download corpora that are ready to go.",
    illustration: Searching,
    to: "/corpus/browse",
    icon: ListIcon
  },
  {
    label: "Chat",
    description: "Ask questions and explore your corpora conversationally.",
    to: "/chat",
    icon: BubblesIcon,
    illustration: MessagingApp
  }
]
