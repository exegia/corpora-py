import type { ElectrobunConfig } from "electrobun";

export default {
	app: {
		name: "CorporaPy",
		identifier: "io.exegia.Corpora",
		version: "0.0.1",
  },
  build: {
		// React Router framework mode (SPA) builds to dist/client/, we copy from there.
		copy: {
			"dist/client/index.html": "views/mainview/index.html",
			"dist/client/assets": "views/mainview/assets",
			// Copy the embedded Python runtime (built via scripts/build/embedded.py)
			// into the app bundle. With current ElectroBun behavior this lands at
			// Contents/lib/app/python/bin/python3 (alongside the app payload).
			// python-bridge.ts now probes both that location and a top-level python/.
			//
			// Admin app: we bundle the (large) full runtime.
			// Client app: base app ships without it (or with minimal). On user opt-in we
			// download the pre-built archive (see scripts/ensure_python_runtime.py).
			"build/lib/python": "python"
    },
		// Ignore Vite output in watch mode — HMR handles view rebuilds separately
		watchIgnore: ["dist/**"],
    targets: "macos-arm64,win-x64",
		// Note: When using `electrobun dev`, the Python runtime must be present in
		// the built dev app. We copy it via the `copy` map above. If you change
		// lib/python, you may need to `rm -rf build` and restart `bun run dev`.
		mac: {
      bundleCEF: false,
		},
		linux: {
			bundleCEF: false,
		},
		win: {
			bundleCEF: false,
		},
	},
} satisfies ElectrobunConfig;
