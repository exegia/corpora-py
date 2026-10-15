import { useAtomValue, useStore } from "jotai"
import { useCallback, useEffect } from "react"
import { resolvedThemeAtom, systemDarkAtom, themeAtom } from "@/shared/store"
import type { ResolvedTheme, Theme } from "@/shared/store-types"

export type { ResolvedTheme, Theme } from "@/shared/store-types"

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

function readPreference(fallback: Theme): Theme {
    try {
        return parseTheme(window.localStorage.getItem(THEME_STORAGE_KEY))
    } catch {
        // Sandboxed webviews may deny storage; retain the in-memory preference.
        return fallback
    }
}

/** Mount at least one consumer for store-bound OS, storage, and DOM synchronization. */
export function useTheme(): ThemeSnapshot & { setTheme: (theme: Theme) => void } {
    const store = useStore()
    const theme = useAtomValue(themeAtom)
    const resolvedTheme = useAtomValue(resolvedThemeAtom)

    useEffect(() => {
        if (typeof window === "undefined") return
        const media =
            typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : undefined
        let restoreTransitions: (() => void) | undefined

        function applyTheme(): void {
            if (typeof document === "undefined") return
            const resolved = store.get(resolvedThemeAtom)
            const root = document.documentElement
            const dark = resolved === "dark"
            if (root.classList.contains("dark") === dark && root.style.colorScheme === resolved) return

            restoreTransitions?.()
            const style = document.createElement("style")
            style.textContent = "*,*::before,*::after{transition:none !important}"
            document.head.appendChild(style)
            // Flush both sides of the swap so removing the stylesheet cannot start color transitions.
            void root.offsetHeight
            root.classList.toggle("dark", dark)
            root.style.colorScheme = resolved
            void root.offsetHeight

            const frame = window.requestAnimationFrame(() => cleanup())
            function cleanup(): void {
                window.cancelAnimationFrame(frame)
                style.remove()
                restoreTransitions = undefined
            }
            restoreTransitions = cleanup
        }

        const onSystemChange = () => store.set(systemDarkAtom, media?.matches ?? false)
        const onStorage = (event: StorageEvent) => {
            if (event.key !== THEME_STORAGE_KEY && event.key !== null) return
            try {
                if (event.storageArea !== window.localStorage) return
            } catch {
                return
            }
            store.set(themeAtom, readPreference(store.get(themeAtom)))
        }
        if (media?.addEventListener) media.addEventListener("change", onSystemChange)
        else media?.addListener(onSystemChange)
        window.addEventListener("storage", onStorage)
        onSystemChange()
        store.set(themeAtom, readPreference(store.get(themeAtom)))
        const unsubscribe = store.sub(resolvedThemeAtom, applyTheme)
        applyTheme()

        return () => {
            unsubscribe()
            if (media?.removeEventListener) media.removeEventListener("change", onSystemChange)
            else media?.removeListener(onSystemChange)
            window.removeEventListener("storage", onStorage)
            restoreTransitions?.()
        }
    }, [store])

    const setTheme = useCallback(
        (preference: Theme): void => {
            if (typeof window === "undefined") return
            try {
                window.localStorage.setItem(THEME_STORAGE_KEY, preference)
            } catch {
                // Theme switching still works when persistence is unavailable.
            }
            store.set(themeAtom, preference)
        },
        [store]
    )

    return { theme, resolvedTheme, setTheme }
}
