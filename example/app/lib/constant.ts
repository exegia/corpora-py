import type { ComponentType, FC, SVGProps } from "react"
import {
  BubblesIcon,
  FileSpreadsheet,
  ListIcon,
  LucideHome,
  LucideUploadCloud,
} from "lucide-react"
import { BoardIllustration } from "~/components/examples/c-empty-14"
import { NodesIllustration } from "~/components/examples/c-empty-19"
import { ChatIllustration } from "~/components/examples/c-empty-17"

export const NAV = [
  { to: "/", label: "Home", icon: LucideHome },
  { to: "/corpus/upload", label: "Upload", icon: LucideUploadCloud },
  { to: "/corpus/convert", label: "Convert", icon: FileSpreadsheet },
  { to: "/chat", label: "Chat", icon: BubblesIcon },
]

type MenuItem = {
  description: string
  illustration?: ComponentType<SVGProps<SVGSVGElement>>
  label: string
  icon?: FC<SVGProps<SVGSVGElement>>
  to: string
}

export const MENU_ITEMS: MenuItem[] = [
  {
    label: "Home",
    description: "Start with the Corpora API tools.",
    icon: LucideHome,
    to: "/",
  },
  {
    label: "Convert",
    description: "Turn a source document into a Text-Fabric dataset.",
    illustration: BoardIllustration,
    icon: LucideUploadCloud,
    to: "/corpus/convert",
  },
  {
    label: "Explore",
    description: "View and download corpora that are ready to go.",
    illustration: NodesIllustration,
    to: "/browse",
    icon: ListIcon,
  },
  {
    label: "Chat",
    description: "Ask questions and explore your corpora conversationally.",
    to: "/chat",
    icon: BubblesIcon,
    illustration: ChatIllustration,
  },
]
