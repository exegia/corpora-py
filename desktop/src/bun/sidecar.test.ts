import { afterAll, afterEach, describe, expect, test } from "bun:test"
import { existsSync, mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { parseSidecarAddress, PythonSidecar, resolvePythonRuntime, type SidecarOptions } from "./sidecar"

const workspaceRoot = resolve(import.meta.dir, "../../..")
const temporary = mkdtempSync(join(tmpdir(), "corpora-sidecar-test-"))
const sidecars: PythonSidecar[] = []
const options: SidecarOptions = {
    development: true,
    workspaceRoot,
    resourcesPath: join(temporary, "Resources"),
    dataPath: join(temporary, "data"),
    env: { ...process.env, AUTH_REQUIRED: "false", LINKING_ENABLED: "false" }
}

afterEach(async () => {
    await Promise.all(sidecars.splice(0).map((sidecar) => sidecar.stop()))
})

function runtimeFile(path: string): void {
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, "")
}

function sidecar(overrides: Partial<SidecarOptions> = {}): PythonSidecar {
    const instance = new PythonSidecar({ ...options, ...overrides })
    sidecars.push(instance)
    return instance
}

describe("runtime resolution", () => {
    test("development uses the workspace venv without inherited Python paths", () => {
        const root = join(temporary, "workspace")
        runtimeFile(join(root, ".venv/bin/python"))
        const result = resolvePythonRuntime({
            ...options,
            workspaceRoot: root,
            platform: "darwin",
            env: { PYTHONHOME: "wrong", PYTHONPATH: "wrong" }
        })
        expect(result.executable).toBe(join(root, ".venv/bin/python"))
        expect(result.cwd).toBe(root)
        expect(result.env.AUTH_REQUIRED).toBe("false")
        expect(result.env.PYTHONHOME).toBeUndefined()
        expect(result.env.PYTHONPATH).toBeUndefined()
    })

    test("development accepts an absolute interpreter override and preserves auth", () => {
        const executable = join(temporary, "custom-python")
        runtimeFile(executable)
        const result = resolvePythonRuntime({ ...options, env: { DEV_PYTHON_BIN: executable, AUTH_REQUIRED: "true" } })
        expect(result.executable).toBe(executable)
        expect(result.env.AUTH_REQUIRED).toBe("true")
        expect(() => resolvePythonRuntime({ ...options, env: { DEV_PYTHON_BIN: "python" } })).toThrow("absolute")
    })

    test("missing development Python explains how to install it", () => {
        expect(() => resolvePythonRuntime({ ...options, workspaceRoot: join(temporary, "missing"), env: {} })).toThrow(
            "uv sync"
        )
    })

    test("packaged builds use app resources, writable cwd and enforced auth", () => {
        const pythonHome = join(options.resourcesPath, "app/python")
        runtimeFile(join(pythonHome, "bin/python3"))
        const result = resolvePythonRuntime({
            ...options,
            development: false,
            platform: "darwin",
            env: { DEV_PYTHON_BIN: "/ignore-me" }
        })
        expect(result.executable).toBe(join(pythonHome, "bin/python3"))
        expect(result.cwd).toBe(options.dataPath)
        expect(result.env.AUTH_REQUIRED).toBe("true")
        expect(result.env.PYTHONHOME).toBe(pythonHome)
        expect(result.env.HF_HOME).toBe(join(options.dataPath, "huggingface"))
    })

    test("Windows interpreter layouts work in development and packaged builds", () => {
        const root = join(temporary, "windows-workspace")
        runtimeFile(join(root, ".venv/Scripts/python.exe"))
        expect(resolvePythonRuntime({ ...options, workspaceRoot: root, platform: "win32", env: {} }).executable).toBe(
            join(root, ".venv/Scripts/python.exe")
        )
        const home = join(options.resourcesPath, "app/python")
        runtimeFile(join(home, "python.exe"))
        expect(resolvePythonRuntime({ ...options, development: false, platform: "win32", env: {} }).executable).toBe(
            join(home, "python.exe")
        )
    })

    test("packaged builds never fall back to system or development Python", () => {
        expect(() =>
            resolvePythonRuntime({
                ...options,
                development: false,
                resourcesPath: join(temporary, "missing-resources"),
                env: { DEV_PYTHON_BIN: "/usr/bin/python3" }
            })
        ).toThrow("sidecar:bundle")
    })
})

describe("discovery records", () => {
    test("ignores third-party log lines", () => {
        expect(parseSidecarAddress("some library log")).toBeNull()
    })

    test("accepts only valid loopback URLs", () => {
        expect(parseSidecarAddress('CORPORA_SIDECAR_LISTENING {"url":"http://127.0.0.1:32123"}')).toBe(
            "http://127.0.0.1:32123"
        )
        for (const url of [
            "http://0.0.0.0:8000",
            "https://example.com",
            "http://127.0.0.1:0",
            "http://127.0.0.1:65536",
            "http://127.0.0.1:8000/path"
        ]) {
            expect(() => parseSidecarAddress(`CORPORA_SIDECAR_LISTENING ${JSON.stringify({ url })}`)).toThrow()
        }
    })

    test("rejects malformed records", () => {
        for (const record of ["null", "{}", "{", '{"url":123}']) {
            expect(() => parseSidecarAddress(`CORPORA_SIDECAR_LISTENING ${record}`)).toThrow()
        }
    })
})

describe("managed Python process", () => {
    test("missing interpreter is surfaced and stopping is idempotent", async () => {
        const instance = sidecar({ pythonExecutable: join(temporary, "no-python") })
        await expect(instance.start()).rejects.toThrow("uv sync")
        expect(instance.getStatus().state).toBe("failed")
        await instance.stop()
        await instance.stop()
    })

    test("health readiness, per-instance ports and graceful shutdown", async () => {
        const first = sidecar()
        const second = sidecar()
        await Promise.all([first.start(), second.start()])
        const firstStatus = first.getStatus()
        const secondStatus = second.getStatus()
        expect(firstStatus.state).toBe("ready")
        expect(firstStatus.authRequired).toBe(false)
        expect(firstStatus.url).not.toBe(secondStatus.url)
        const response = await fetch(`${firstStatus.url}/health`)
        expect(await response.json()).toEqual({ status: "ok" })
        await Promise.all([first.stop(), second.stop()])
        expect(first.getStatus().state).toBe("stopped")
        await expect(fetch(`${firstStatus.url}/health`)).rejects.toThrow()
    }, 30000)

    test("packaged auth default remains enforced by the existing API", async () => {
        // Explicit auth-on also exercises the same API gate in a workspace interpreter.
        const instance = sidecar({ env: { ...options.env, AUTH_REQUIRED: "true" } })
        await instance.start()
        expect(instance.getStatus().authRequired).toBe(true)
        const response = await fetch(`${instance.getStatus().url}/convert/unknown`)
        expect(response.status).toBe(401)
    }, 20000)

    test.skipIf(!existsSync(resolve(import.meta.dir, "../../resources/python")))(
        "standalone bundle starts without the workspace and preserves auth",
        async () => {
            const resourcesPath = join(temporary, "bundled-resources")
            mkdirSync(join(resourcesPath, "app"), { recursive: true })
            symlinkSync(
                resolve(import.meta.dir, "../../resources/python"),
                join(resourcesPath, "app/python"),
                process.platform === "win32" ? "junction" : "dir"
            )
            const env = { ...options.env }
            delete env.AUTH_REQUIRED
            // -P must keep writable application data off Python's import path.
            runtimeFile(join(temporary, "bundled-data/corpora_py/__init__.py"))
            writeFileSync(
                join(temporary, "bundled-data/corpora_py/__init__.py"),
                'raise RuntimeError("shadowed bundled package")'
            )
            const instance = sidecar({
                development: false,
                resourcesPath,
                dataPath: join(temporary, "bundled-data"),
                env
            })
            await instance.start()
            expect(instance.getStatus().state).toBe("ready")
            expect(instance.getStatus().authRequired).toBe(true)
            expect((await fetch(`${instance.getStatus().url}/convert/unknown`)).status).toBe(401)
            await instance.stop()
            expect(instance.getStatus().state).toBe("stopped")
        },
        30000
    )

    test("shutdown during startup does not leave a live backend", async () => {
        const instance = sidecar()
        const starting = instance.start().then(
            () => null,
            (error: unknown) => error
        )
        await instance.stop()
        const error = await starting
        expect(error).toBeInstanceOf(Error)
        expect(error instanceof Error ? error.message : "").toContain("cancelled")
        expect(instance.getStatus().state).toBe("stopped")
    }, 10000)

    test("startup timeout tears down the child", async () => {
        const instance = sidecar({ startupTimeoutMs: 1 })
        await expect(instance.start()).rejects.toThrow("startup timeout")
        expect(instance.getStatus().state).toBe("failed")
    }, 10000)

    test("unexpected process exit is reported to the renderer", async () => {
        const instance = sidecar()
        await instance.start()
        instance.forceStop()
        const deadline = Date.now() + 3000
        while (instance.getStatus().state === "ready" && Date.now() < deadline) {
            await new Promise((done) => setTimeout(done, 25))
        }
        expect(instance.getStatus().state).toBe("failed")
        expect(instance.getStatus().url).toBeNull()
    }, 20000)
})

afterAll(() => rmSync(temporary, { recursive: true, force: true }))
