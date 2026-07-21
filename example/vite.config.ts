import { reactRouter } from "@react-router/dev/vite"
import tailwindcss from "@tailwindcss/vite"
import devtoolsJson from "vite-plugin-devtools-json"
import { defineConfig } from "vite"

export default defineConfig({
  resolve: { tsconfigPaths: true },
  plugins: [tailwindcss(), reactRouter(), devtoolsJson()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    open: true,
    // PORT is set by launchers (e.g. the preview harness with autoPort);
    // fall back to 5173 for plain `bun run vite:dev`.
    port: process.env.PORT ? Number(process.env.PORT) : 5173,
    strictPort: Boolean(process.env.PORT),
  },
})
