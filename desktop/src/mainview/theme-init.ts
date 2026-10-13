import { parseTheme, resolveTheme, THEME_STORAGE_KEY } from "@/hooks/use-theme"

// Resolve appearance before React mounts, including when webview storage is unavailable.
let preference = parseTheme(null)
try {
    preference = parseTheme(window.localStorage.getItem(THEME_STORAGE_KEY))
} catch {}
const resolved = resolveTheme(preference, window.matchMedia("(prefers-color-scheme: dark)").matches)
document.documentElement.classList.toggle("dark", resolved === "dark")
document.documentElement.style.colorScheme = resolved
