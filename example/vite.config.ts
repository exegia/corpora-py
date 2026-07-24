import { reactRouter } from "@react-router/dev/vite"
import tailwindcss from "@tailwindcss/vite"
import devtoolsJson from "vite-plugin-devtools-json"
import { defineConfig, loadEnv } from "vite"

export default defineConfig(({ mode }) => {
  // The free-chat gateway credential for LOCAL dev. In production the
  // api/gateway/[path].ts function proxies with the deployment's own
  // credential; the vite dev server has no function runtime, so it proxies
  // /api/gateway to the real gateway itself, authenticated with whatever
  // `vercel env pull .env.local` provisioned (VERCEL_OIDC_TOKEN, ~24h) or an
  // explicit AI_GATEWAY_API_KEY. Third argument "" exposes non-VITE_ vars to
  // this config only — nothing here reaches the client bundle.
  const env = loadEnv(mode, process.cwd(), "")
  const gatewayToken = env.AI_GATEWAY_API_KEY ?? env.VERCEL_OIDC_TOKEN ?? ""

  return {
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
      proxy: {
        "/api/gateway": {
          target: "https://ai-gateway.vercel.sh",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/gateway/, "/v4/ai"),
          headers: { Authorization: `Bearer ${gatewayToken}` },
        },
      },
    },
  }
})
