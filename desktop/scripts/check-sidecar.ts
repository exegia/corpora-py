import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { resolve } from "node:path"

const home = resolve(import.meta.dir, "../resources/python")
const executable = resolve(home, process.platform === "win32" ? "python.exe" : "bin/python3")
if (!existsSync(executable)) {
    throw new Error("Bundled Python is missing. Run hutch run sidecar:bundle, then retry the release build.")
}
const env: NodeJS.ProcessEnv = { ...process.env, PYTHONHOME: home, PYTHONNOUSERSITE: "1", PYTHONDONTWRITEBYTECODE: "1" }
delete env.PYTHONPATH
const result = spawnSync(executable, ["-P", "-c", "import corpora_py.sidecar"], {
    env,
    stdio: "inherit",
    timeout: 10000,
    windowsHide: true
})
if (result.error || result.status !== 0) {
    throw new Error("Bundled Python cannot import corpora_py.sidecar. Rebuild it with hutch run sidecar:bundle.")
}
console.log("Bundled Corpora Python runtime is ready to package.")
