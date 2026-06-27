import type { ElectrobunConfig } from "electrobun";

export default {
	app: {
		name: "corpora python test",
		identifier: "io.exegia.Corpora",
		version: "0.0.1",
	},
	build: {
		// Vite builds to dist/, we copy from there
		copy: {
			"dist/index.html": "views/mainview/index.html",
			"dist/assets": "views/mainview/assets",
			// Copy the embedded Python runtime (built via build:python) into the app bundle
			// so python-bridge.ts can find it at Contents/Resources/python/bin/python3
			"resources/python": "python",
		},
		// Ignore Vite output in watch mode — HMR handles view rebuilds separately
		watchIgnore: ["dist/**"],

		// Note: When using `electrobun dev`, the Python runtime must be present in
		// the built dev app. We copy it via the `copy` map above. If you change
		// resources/python, you may need to `rm -rf build` and restart `bun run dev`.
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
