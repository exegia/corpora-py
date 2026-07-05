import { useWebSocket } from "@/hooks/use-socket"
import type { BridgeStatus } from "@/types/socket"
import { Chip, ChipRootProps } from "@heroui/react"
import { Check, Clock, CloudOff, Stop } from "@untitledui/icons"
import { Button } from "@astryxdesign/core/Button"
import { SVGAttributes } from "react"

type ChipStatus = ChipRootProps["color"]
type ChipStatusMap<T extends BridgeStatus = BridgeStatus> = Record<T, {
  color: ChipStatus,
  icon: React.FC<SVGAttributes<SVGSVGElement>>,
  label: T
}>

const chipStatus: ChipStatusMap = {
  "open": { color: "success", icon: Check, label: "open" },
  "closed": { color: "danger", icon: Stop, label: "closed" },
  "connecting": { color: "warning", icon: Clock, label: "connecting" },
  "error": { color: "danger", icon: Stop, label: "error" },
  "idle": { color: "default", icon: CloudOff, label: "idle" }
}

export const StatusBar = () => {

  const { status } = useWebSocket()

  const IconComponent = chipStatus[status].icon
  return (
    <div className="flex flex-row w-full items-center absolute left-0 bottom-0">
      <div
        className="bg-white/80 dark:bg-neutral-700/30 backdrop-blur-md mx-auto px-3 py-2 mb-3 rounded-xl flex flex-row items-center gap-2 justify-between w-lg">
        <Button label="Connect" variant="secondary" size={"sm"} />
        <Chip color={chipStatus[status].color} variant="soft">
          <IconComponent width={12} />
          <Chip.Label className="capitalize">{chipStatus[status].label}</Chip.Label>
        </Chip>
      </div>
    </div>
  )
}
