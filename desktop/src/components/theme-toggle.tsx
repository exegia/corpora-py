import { Monitor, Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { nextTheme, useTheme } from "@/hooks/use-theme"

export interface ThemeToggleProps {
    className?: string
    disabled?: boolean
}

export function ThemeToggle({ className, disabled }: ThemeToggleProps) {
    const { theme, resolvedTheme, setTheme } = useTheme()
    const next = nextTheme(theme)
    const Icon = theme === "system" ? Monitor : theme === "light" ? Sun : Moon
    const current = theme === "system" ? `system (${resolvedTheme})` : theme
    const label = `Theme: ${current}. Switch to ${next} theme`

    return (
        <Button
            type="button"
            variant="ghost"
            size="icon"
            className={className}
            disabled={disabled}
            aria-label={label}
            title={label}
            onClick={() => setTheme(next)}
        >
            <Icon aria-hidden="true" strokeWidth={2} />
        </Button>
    )
}
