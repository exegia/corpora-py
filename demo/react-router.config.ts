import type { Config } from "@react-router/dev/config";

export default {
	// This app is packaged inside an Electrobun desktop webview — there is no
	// long-running server to render on. Run framework mode as a client-rendered
	// SPA (matches the previous createRoot setup).
	ssr: false,
	// Route modules live in app/ (the default), e.g. app/routes.ts + app/routes/*.
	appDirectory: "app",
	// Emit the SPA build to dist/ so electrobun.config.ts can copy
	// dist/client/index.html + dist/client/assets into the app bundle.
	buildDirectory: "dist",
} satisfies Config;
