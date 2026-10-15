import { parseTheme, THEME_STORAGE_KEY } from "@/hooks/use-theme"
import { resolvedThemeAtom, store, systemDarkAtom, themeAtom } from "@/shared/store"

// Resolve appearance before React mounts, including when webview storage is unavailable.
let preference = store.get(themeAtom)
try {
    preference = parseTheme(window.localStorage.getItem(THEME_STORAGE_KEY))
} catch {}
store.set(themeAtom, preference)
store.set(
    systemDarkAtom,
    typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches
)
const resolved = store.get(resolvedThemeAtom)
document.documentElement.classList.toggle("dark", resolved === "dark")
document.documentElement.style.colorScheme = resolved
