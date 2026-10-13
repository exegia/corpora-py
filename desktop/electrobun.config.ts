import type { ElectrobunConfig } from "electrobun"
import { existsSync } from "node:fs"
import { resolve } from "node:path"

export default {
    app: {
        name: "react-tailwind-vite",
        identifier: "reacttailwindvite.electrobun.dev",
        version: "0.0.1"
    },
    build: {
        mainProcess: "cottontail",
        cottontail: {
            entrypoint: "src/bun/index.ts",
            define: {
                CORPORA_WORKSPACE_ROOT: JSON.stringify(resolve(import.meta.dir, ".."))
            }
        },
        // Vite builds to dist/, we copy from there
        copy: {
            "dist/index.html": "views/mainview/index.html",
            "dist/assets": "views/mainview/assets",
            // Development uses .venv; release scripts require the standalone runtime.
            ...(existsSync(resolve(import.meta.dir, "resources/python")) ? { "resources/python": "python" } : {})
        },
        // Ignore Vite output in watch mode — HMR handles view rebuilds separately
        watchIgnore: ["dist/**", "resources/**", "src/**/*.test.ts"],
        mac: {
            bundleCEF: false
        },
        linux: {
            bundleCEF: false
        },
        win: {
            bundleCEF: false
        }
    }
} satisfies ElectrobunConfig
