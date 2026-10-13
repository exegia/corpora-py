import Logo from "@/components/logo"
import { ThemeToggle } from "@/components/theme-toggle"

export function TitleBar() {
    return (
        <header className="desktop-titlebar electrobun-webkit-app-region-drag flex h-13 shrink-0 select-none items-center justify-between gap-4 border-b border-border bg-card pr-4">
            <div className="pointer-events-none flex items-center gap-2.5">
                <Logo
                    aria-hidden="true"
                    focusable="false"
                    className="size-6 text-primary"
                />
                <span className="text-sm font-semibold tracking-tight">Corpora</span>
                <span className="hidden border-l border-border pl-2.5 text-xs text-muted-foreground sm:inline">
                    Local workspace
                </span>
            </div>
            <div className="electrobun-webkit-app-region-no-drag flex items-center gap-2">
                <ThemeToggle />
            </div>
        </header>
    )
}
