import { Settings, StarIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "tailwind-variants"

export interface SettingsButtonProps {
    className?: string
    onClick?: () => void
}

export const SettingsButton = ({ className, onClick }: SettingsButtonProps) => (
    <Button
        size="icon-md"
        variant="ghost"
        className={cn("rounded-full", className)}
        onClick={onClick}>
        <Settings />
    </Button>
)
