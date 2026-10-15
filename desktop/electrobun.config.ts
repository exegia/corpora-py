import type { ElectrobunConfig } from "electrobun"
import { existsSync } from "node:fs"
import { resolve } from "node:path"

export default {
    app: {
        name: "Corpora",
        identifier: "desktop.corpora.exegia.dev",
        version: "0.0.1",
        description: "Corpora Desktop app + Python sidecar to perform proof of concept and reliability",
        fileAssociations: [
            {
                name: "corpora",
                role: "Editor",
                ext: ["csux", "ctei", "corpus"]
            },
            {
                name: "conversion",
                role: "Viewer",
                ext: ["epub", "txt", "pdf"]
            }
        ]
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
