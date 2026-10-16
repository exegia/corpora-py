import Electrobun, { BrowserView, BrowserWindow, BuildConfig, PATHS, Utils } from "electrobun/main"
import type { DesktopRPC } from "../shared/rpc"
import { PythonSidecar } from "./sidecar"
import { DESKTOP_DEFAULT_FRAME, enforceMinimumWindowWidth } from "./window-layout"

// Injected by the Electrobun build; never used to locate Python in a packaged app.
declare const CORPORA_WORKSPACE_ROOT: string

const DEV_SERVER_URL = "http://localhost:5173"
const development = !BuildConfig.getSync().isPackaged
const sidecar = new PythonSidecar({
    development,
    workspaceRoot: CORPORA_WORKSPACE_ROOT,
    resourcesPath: PATHS.RESOURCES_FOLDER,
    dataPath: Utils.paths.userData
})

let quitting = false
let shutdownComplete = false
Electrobun.events.on("before-quit", (event: { response: { allow: boolean } }) => {
    if (shutdownComplete) return
    // Electrobun's veto is synchronous; resume quitting only after cleanup finishes.
    event.response = { allow: false }
    if (quitting) return
    quitting = true
    void sidecar.stop().finally(() => {
        shutdownComplete = true
        Utils.quit()
    })
})
process.on("SIGINT", () => Utils.quit())
process.on("SIGTERM", () => Utils.quit())
process.once("exit", () => sidecar.forceStop())

const rpc = BrowserView.defineRPC<DesktopRPC>({
    handlers: {
        requests: { getSidecarStatus: () => sidecar.getStatus() },
        messages: {}
    }
})

// Keep a window available during startup, including when Python is missing or crashes.
void sidecar.start().catch((error: unknown) => {
    console.error("Corpora sidecar startup failed:", error)
})

async function getMainViewUrl(): Promise<string> {
    if (development) {
        try {
            const response = await fetch(DEV_SERVER_URL, { method: "HEAD", signal: AbortSignal.timeout(1000) })
            if (response.ok) return DEV_SERVER_URL
        } catch {
            console.log("Vite is not running; using bundled view assets.")
        }
    }
    return "views://mainview/index.html"
}

try {
    const mainWindow = new BrowserWindow({
        title: "Corpora",
        titleBarStyle: "hiddenInset",
        passthrough: false,
        allowedProtocols: { views: true, appData: true },
        url: await getMainViewUrl(),
        trafficLightOffset: { x: 6, y: 6 },
        rpc,
        frame: DESKTOP_DEFAULT_FRAME
    })
    enforceMinimumWindowWidth(mainWindow)
    if (process.platform === "darwin") {
        // Electrobun 2.0.2 uses absolute left/top insets, not deltas. Native
        // buttons are 14pt tall: a 15pt top inset centers them in our 44pt bar.
        //  mainWindow.setWindowButtonPosition(16, (44 - 14) / 2)
    }
    mainWindow.webview.setNavigationRules(["^*", "views://mainview/*", ...(development ? [`${DEV_SERVER_URL}/*`] : [])])
} catch (error) {
    await sidecar.stop()
    throw error
}
