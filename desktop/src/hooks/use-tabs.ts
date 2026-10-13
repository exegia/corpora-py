
import { TTabItem } from "@/shared/navigation"
import { useRef, useState } from "react"

export const useTabs = () => {
  const [activeTab, setActiveTab] = useState <TTabItem['id']>("dashboard")
  const tabTriggers = useRef<Record<string, HTMLButtonElement | null>>({})
  const navigateTo = (value: string) => {
      setActiveTab(value)
      tabTriggers.current[value]?.focus()
  }
}
