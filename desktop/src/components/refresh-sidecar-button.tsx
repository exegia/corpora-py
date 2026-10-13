import type { ReactElement } from "react"
import { RefreshCw } from "lucide-react"
import { Button as SharkButton } from "@/components/ui/shark-button"

export interface RefreshSidecarButtonProps {
    isChecking: boolean
    onRefresh: () => void
    compact?: boolean
}

export function RefreshSidecarButton({
    isChecking,
    onRefresh,
    compact = false
}: RefreshSidecarButtonProps): ReactElement {
    return (
        <SharkButton
            type="button"
            variant="outline"
            size={compact ? "xs" : "sm"}
            isLoading={isChecking}
            disabled={isChecking}
            aria-label={compact ? "Check sidecar now" : undefined}
            onClick={onRefresh}>
            <RefreshCw aria-hidden="true" />
            {isChecking ? "Checking sidecar…" : compact ? "Check" : "Check sidecar"}
        </SharkButton>
    )
}
