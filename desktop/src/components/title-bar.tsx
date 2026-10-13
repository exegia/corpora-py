import Logo from "@/components/logo"
import { SettingsButton } from "./settings-button"

export function TitleBar() {
    return (
        <header className="desktop-titlebar electrobun-webkit-app-region-drag flex h-11 shrink-0 select-none items-center justify-between gap-3 border-b border-border bg-card pr-3">
            <div className="pointer-events-none flex items-center gap-1">
                <Logo
                    aria-hidden="true"
                    focusable="false"
                    className="size-4 text-primary"
                />
                <span className="text-sm font-normal font-serif tracking-tight">Corpora</span>
            </div>
            <div className="electrobun-webkit-app-region-no-drag flex items-center gap-2">
                <SettingsButton />
            </div>
        </header>
    )
}
