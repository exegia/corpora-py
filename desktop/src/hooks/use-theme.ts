import { useSyncExternalStore } from "react"

export type Theme = "system" | "light" | "dark"
export type ResolvedTheme = Exclude<Theme, "system">

// Shared with the pre-render appearance initialization in theme-init.ts.
export const THEME_STORAGE_KEY = "corpora-desktop-theme"

export function parseTheme(value: unknown): Theme {
    return value === "light" || value === "dark" ? value : "system"
}

export function nextTheme(theme: Theme): Theme {
    return theme === "system" ? "light" : theme === "light" ? "dark" : "system"
}

export function resolveTheme(theme: Theme, systemDark: boolean): ResolvedTheme {
    return theme === "system" ? (systemDark ? "dark" : "light") : theme
}

interface ThemeSnapshot {
    readonly theme: Theme
    readonly resolvedTheme: ResolvedTheme
}

const serverSnapshot: ThemeSnapshot = { theme: "system", resolvedTheme: "light" }
let snapshot = serverSnapshot
const listeners = new Set<() => void>()
let media: MediaQueryList | undefined
let stopListening: (() => void) | undefined
let restoreTransitions: (() => void) | undefined

function readPreference(): Theme {
    try {
        return parseTheme(window.localStorage.getItem(THEME_STORAGE_KEY))
    } catch {
        // Sandboxed webviews may deny storage; retain the in-memory preference.
        return snapshot.theme
    }
}

function systemIsDark(): boolean {
    return (
        media?.matches ??
        (typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches)
    )
}

function applyTheme(resolvedTheme: ResolvedTheme): void {
    if (typeof document === "undefined") return
    const root = document.documentElement
    const dark = resolvedTheme === "dark"
    if (root.classList.contains("dark") === dark && root.style.colorScheme === resolvedTheme) return

    restoreTransitions?.()
    const style = document.createElement("style")
    style.textContent = "*,*::before,*::after{transition:none !important}"
    document.head.appendChild(style)
    // Flush both sides of the swap so removing the stylesheet cannot start color transitions.
    void root.offsetHeight
    root.classList.toggle("dark", dark)
    root.style.colorScheme = resolvedTheme
    void root.offsetHeight

    const frame = window.requestAnimationFrame(() => cleanup())
    function cleanup(): void {
        window.cancelAnimationFrame(frame)
        style.remove()
        restoreTransitions = undefined
    }
    restoreTransitions = cleanup
}

function update(theme: Theme): void {
    const resolvedTheme = resolveTheme(theme, systemIsDark())
    applyTheme(resolvedTheme)
    if (snapshot.theme === theme && snapshot.resolvedTheme === resolvedTheme) return
    snapshot = { theme, resolvedTheme }
    for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
    if (typeof window === "undefined") return () => {}
    listeners.add(listener)
    if (listeners.size === 1) {
        media = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : undefined
        const onSystemChange = () => update(snapshot.theme)
        const onStorage = (event: StorageEvent) => {
            if (event.key !== THEME_STORAGE_KEY && event.key !== null) return
            try {
                if (event.storageArea !== window.localStorage) return
            } catch {
                return
            }
            update(readPreference())
        }
        if (media?.addEventListener) media.addEventListener("change", onSystemChange)
        else media?.addListener(onSystemChange)
        window.addEventListener("storage", onStorage)
        stopListening = () => {
            if (media?.removeEventListener) media.removeEventListener("change", onSystemChange)
            else media?.removeListener(onSystemChange)
            window.removeEventListener("storage", onStorage)
            media = undefined
            restoreTransitions?.()
        }
        update(readPreference())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            stopListening?.()
            stopListening = undefined
        }
    }
}

function setTheme(theme: Theme): void {
    if (typeof window === "undefined") return
    try {
        window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
        // Theme switching still works when persistence is unavailable.
    }
    update(theme)
}

const getSnapshot = () => snapshot
const getServerSnapshot = () => serverSnapshot

/** Shared across all consumers; mount at least one consumer for system-theme updates. */
export function useTheme(): ThemeSnapshot & { setTheme: (theme: Theme) => void } {
    const current = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
    return { ...current, setTheme }
}
