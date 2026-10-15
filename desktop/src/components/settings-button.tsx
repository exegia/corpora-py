import { Settings } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export interface SettingsButtonProps {
    className?: string
    onClick?: () => void
}

export const SettingsButton = ({ className, onClick }: SettingsButtonProps) => (
    <Button
        type="button"
        aria-label="Open settings"
        size="icon-md"
        variant="ghost"
        className={cn("rounded-full", className)}
        onClick={onClick}>
        <Settings aria-hidden="true" />
    </Button>
)
