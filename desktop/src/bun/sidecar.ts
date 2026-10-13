import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process"
import { existsSync, mkdirSync } from "node:fs"
import { isAbsolute, join, resolve } from "node:path"
import type { SidecarStatus } from "../shared/rpc"

const DISCOVERY_PREFIX = "CORPORA_SIDECAR_LISTENING "

export interface SidecarOptions {
    readonly development: boolean
    readonly workspaceRoot: string
    readonly resourcesPath: string
    readonly dataPath: string
    readonly pythonExecutable?: string
    readonly platform?: NodeJS.Platform
    readonly env?: NodeJS.ProcessEnv
    readonly startupTimeoutMs?: number
}

export function resolvePythonRuntime(options: SidecarOptions): {
    executable: string
    cwd: string
    env: NodeJS.ProcessEnv
} {
    const platform = options.platform ?? process.platform
    const env = { ...(options.env ?? process.env) }
    // An inherited virtualenv must not redirect a bundled interpreter's imports.
    delete env.PYTHONHOME
    delete env.PYTHONPATH
    env.PYTHONNOUSERSITE = "1"
    env.PYTHONDONTWRITEBYTECODE = "1"
    env.PYTHONUNBUFFERED = "1"

    if (options.development) {
        const override = options.pythonExecutable ?? env.DEV_PYTHON_BIN
        if (override && !isAbsolute(override)) {
            throw new Error("DEV_PYTHON_BIN must be an absolute path to a Python interpreter.")
        }
        const executable =
            override ??
            join(options.workspaceRoot, platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python")
        if (!existsSync(executable)) {
            throw new Error(`Python not found at ${executable}. Run uv sync from the repository root.`)
        }
        env.AUTH_REQUIRED ??= "false"
        return { executable, cwd: options.workspaceRoot, env }
    }

    const pythonHome = join(options.resourcesPath, "app", "python")
    const executable = join(pythonHome, platform === "win32" ? "python.exe" : "bin/python3")
    if (!existsSync(executable)) {
        throw new Error("Bundled Python is missing. Run hutch run sidecar:bundle before building the desktop app.")
    }
    mkdirSync(options.dataPath, { recursive: true })
    env.PYTHONHOME = pythonHome
    env.HF_HOME ??= join(options.dataPath, "huggingface")
    env.AUTH_REQUIRED ??= "true"
    return { executable, cwd: options.dataPath, env }
}

export function parseSidecarAddress(line: string): string | null {
    if (!line.startsWith(DISCOVERY_PREFIX)) return null
    const payload: unknown = JSON.parse(line.slice(DISCOVERY_PREFIX.length))
    if (typeof payload !== "object" || payload === null || !("url" in payload) || typeof payload.url !== "string") {
        throw new Error("Invalid Python sidecar discovery record.")
    }
    const match = /^http:\/\/127\.0\.0\.1:(\d+)$/.exec(payload.url)
    if (!match || Number(match[1]) < 1 || Number(match[1]) > 65535) {
        throw new Error("Python sidecar must announce an IPv4 loopback address.")
    }
    return payload.url
}

async function probeBackend(url: string): Promise<boolean | null> {
    try {
        const health = await fetch(`${url}/health`, { signal: AbortSignal.timeout(1000), redirect: "error" })
        if (!health.ok) return null
        const payload: unknown = await health.json()
        if (typeof payload !== "object" || payload === null || !("status" in payload) || payload.status !== "ok")
            return null
        const response = await fetch(`${url}/capabilities`, { signal: AbortSignal.timeout(1000), redirect: "error" })
        if (!response.ok) return null
        const capabilities: unknown = await response.json()
        if (typeof capabilities !== "object" || capabilities === null || !("auth_required" in capabilities)) return null
        return typeof capabilities.auth_required === "boolean" ? capabilities.auth_required : null
    } catch {
        // Discovery precedes app startup, so connection failures are expected until ready.
        return null
    }
}

const sleep = (ms: number): Promise<void> => new Promise((done) => setTimeout(done, ms))

function waitForExit(child: ChildProcessWithoutNullStreams, timeoutMs: number): Promise<boolean> {
    if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true)
    return new Promise((done) => {
        const onClose = () => {
            clearTimeout(timer)
            done(true)
        }
        const timer = setTimeout(() => {
            child.off("close", onClose)
            done(false)
        }, timeoutMs)
        child.once("close", onClose)
    })
}

export class PythonSidecar {
    private child: ChildProcessWithoutNullStreams | null = null
    private stopping = false
    private stopPromise: Promise<void> | null = null
    private status: SidecarStatus = { state: "starting", url: null, error: null, authRequired: null }

    constructor(private readonly options: SidecarOptions) {}

    getStatus(): SidecarStatus {
        return { ...this.status }
    }

    async start(): Promise<void> {
        if (this.child || this.stopping) throw new Error("Python sidecar cannot be started twice.")
        try {
            const runtime = resolvePythonRuntime(this.options)
            const child = spawn(runtime.executable, ["-P", "-u", "-m", "corpora_py.sidecar", "--watch-parent"], {
                cwd: resolve(runtime.cwd),
                env: runtime.env,
                stdio: ["pipe", "pipe", "pipe"],
                windowsHide: true
            })
            this.child = child
            child.on("error", (error) => this.fail(`Could not launch Python: ${error.message}`))
            child.on("close", (code, signal) => {
                if (!this.stopping) {
                    this.fail(`Python exited (${signal ?? code}). Check the main-process logs for the traceback.`)
                }
            })
            child.stdin.on("error", (error) => {
                if (!this.stopping) this.fail(`Python control pipe failed: ${error.message}`)
            })
            child.stderr.on("data", (chunk: Buffer) => process.stderr.write(chunk))
            child.stdout.setEncoding("utf8")
            let buffer = ""
            child.stdout.on("data", (chunk: string) => {
                buffer += chunk
                let newline = buffer.indexOf("\n")
                while (newline !== -1) {
                    const line = buffer.slice(0, newline).trimEnd()
                    buffer = buffer.slice(newline + 1)
                    try {
                        const url = parseSidecarAddress(line)
                        if (url && !this.stopping && this.status.state === "starting") {
                            this.status = { ...this.status, url }
                        } else if (!url) {
                            console.log(`[python] ${line}`)
                        }
                    } catch (error) {
                        this.fail(error instanceof Error ? error.message : String(error))
                    }
                    newline = buffer.indexOf("\n")
                }
                // Third-party output without a newline must not grow memory indefinitely.
                if (buffer.length > 16384) buffer = buffer.slice(-16384)
            })

            const deadline = Date.now() + (this.options.startupTimeoutMs ?? 60000)
            while (Date.now() < deadline) {
                if (this.stopping) throw new Error("Python sidecar startup was cancelled.")
                if (this.status.state === "failed") throw new Error(this.status.error ?? "Python startup failed.")
                const url = this.status.url
                if (url) {
                    const authRequired = await probeBackend(url)
                    if (authRequired !== null && !this.stopping && this.status.state === "starting") {
                        this.status = { state: "ready", url, error: null, authRequired }
                        console.log(`Corpora Python sidecar ready at ${url}`)
                        return
                    }
                }
                await sleep(100)
            }
            throw new Error(
                "Python sidecar did not become ready within the startup timeout. Check the main-process logs."
            )
        } catch (error) {
            if (!this.stopping) this.fail(error instanceof Error ? error.message : String(error))
            await this.stop()
            throw error
        }
    }

    private fail(message: string): void {
        if (!this.stopping && this.status.state !== "failed") {
            this.status = { state: "failed", url: null, error: message, authRequired: null }
            console.error(message)
        }
    }

    stop(): Promise<void> {
        if (this.stopPromise) return this.stopPromise
        this.stopping = true
        if (this.status.state !== "failed") {
            this.status = { state: "stopped", url: null, error: null, authRequired: null }
        }
        this.stopPromise = this.stopChild()
        return this.stopPromise
    }

    private async stopChild(): Promise<void> {
        const child = this.child
        if (!child) return
        // EOF requests graceful shutdown on Windows as well as Unix.
        child.stdin.end()
        if (!(await waitForExit(child, 5000))) {
            child.kill("SIGKILL")
            await waitForExit(child, 1000)
        }
    }

    forceStop(): void {
        this.child?.kill("SIGKILL")
    }
}
