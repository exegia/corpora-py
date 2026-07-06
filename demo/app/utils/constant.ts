import { HomeLine, UploadCloud01, FileCheck02, Terminal } from "@untitledui/icons"
import type { ComponentType, FC, SVGProps } from "react"
import { FilesUploadingIllustration, KeyPointsIllustration, OpenBookIllustration } from "@/assets"
import { BubblesIcon, ListIcon } from "lucide-react"

export const NAV = [
  { to: "/", label: "Home", icon: HomeLine },
  { to: "/corpus/upload", label: "Upload", icon: UploadCloud01 },
  { to: "/corpus/convert", label: "Convert", icon: FileCheck02 },
  { to: "/logs", label: "Logs", icon: Terminal }
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
    illustration: FilesUploadingIllustration,
    icon: HomeLine,
    to: "/"
  },
  {
    label: "Convert",
    description: "Turn a source document into a Text-Fabric dataset.",
    illustration: FilesUploadingIllustration,
    icon: UploadCloud01,
    to: "/corpus/convert"
  },
  {
    label: "Explore",
    description: "View and download corpora that are ready to go.",
    illustration: OpenBookIllustration,
    to: "/corpus/browse",
    icon: ListIcon
  },
  {
    label: "Chat",
    description: "Ask questions and explore your corpora conversationally.",
    to: "/chat",
    icon: BubblesIcon,
    illustration: KeyPointsIllustration
  }
]
