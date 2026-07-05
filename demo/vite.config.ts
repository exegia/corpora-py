import { defineConfig } from "vite"
import { reactRouter } from "@react-router/dev/vite"
import tailwindcss from "@tailwindcss/vite"
import { resolve } from "path"

export default defineConfig({
  // Framework mode: the reactRouter() plugin owns the app dir (./app) and the
  // build output (configured via react-router.config.ts -> buildDirectory "dist",
  // emitting dist/client for the SPA build). It also provides React/Fast Refresh,
  // so we no longer use @vitejs/plugin-react or a `root`/`build.outDir` override
  // (that was the old src/mainview SPA setup).
  plugins: [tailwindcss(), reactRouter()],
  resolve: {
    // Vite 8 dev resolves bare `@/…` imports via tryNodeResolve with
    // tsconfigPaths off by default; enable it so demo/tsconfig.json paths work.
    tsconfigPaths: true,
    alias: {
      "@": resolve(import.meta.dirname, "app")
    }
  },
  build: {
    outDir: "dist",
    emptyOutDir: true
  },
  appType: "spa",
  root: ".",
  server: {
    open: true,
    port: 5173,
    strictPort: true
  }
})
