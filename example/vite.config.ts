import { reactRouter } from "@react-router/dev/vite"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

export default defineConfig({
  resolve: { tsconfigPaths: true },
  plugins: [tailwindcss(), reactRouter()],
  build: {
    outDir: "dist",
    emptyOutDir: true
  },
  server: {
    open: true,
    port: 5173,
    strictPort: true
  }
})
