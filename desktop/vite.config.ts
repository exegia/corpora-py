import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { electrobunViteAliases } from "./.hutch/devkit/api/config/electrobun-vite"

export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: [
            ...electrobunViteAliases(resolve(__dirname, ".hutch/devkit")),
            // Mirrors tsconfig's "@/*" path, which shadcn/ReUI components import from.
            { find: /^@\//, replacement: `${resolve(__dirname, "src")}/` }
        ]
    },
    root: "src/mainview",

    build: {
        outDir: "../../dist",
        emptyOutDir: true
    },
    server: {
        port: 5173,
        strictPort: true,
        host: "0.0.0.0",
        hmr: {
            port: 5173,
            host: "0.0.0.0"
        }
    }
})
