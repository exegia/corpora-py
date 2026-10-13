// @hutch cli=0.27.1 cottontail=0.7.1
export default {
    scripts: {
        install: ["hutch", "install", "--frozen-lockfile"],
        setup: ["uv", "sync", "--project", ".."],
        typecheck: ["bun", "run", "--bun", "tsc", "--noEmit"],
        test: "hutch test src/bun/sidecar.test.ts && env bun test src/lib src/components",
        "sidecar:bundle": [
            "make",
            "-C",
            "..",
            "build-bundle",
            "BUILD_ARGS=--out-dir dist --dest-dir desktop/resources/python --skip-sign"
        ],
        "sidecar:check": ["hutch", "scripts/check-sidecar.ts"],
        // `env` bypasses Cottontail's built-in `bun` command to use the installed Bun runtime.
        start: "hutch electrobun prepare && env bun run --bun vite build && hutch electrobun dev",
        dev: "hutch electrobun prepare && env bun run --bun vite build && hutch electrobun dev --watch",
        "dev:hmr": ["bun", "run", "--bun", "concurrently", "--kill-others-on-fail", "hutch run hmr", "hutch run start"],
        hmr: "hutch electrobun prepare && env bun run --bun vite --port 5173 --strictPort",
        build: "hutch run sidecar:check && hutch electrobun prepare && env bun run --bun vite build && hutch electrobun build --env=stable",
        "build:canary":
            "hutch run sidecar:check && hutch electrobun prepare && env bun run --bun vite build && hutch electrobun build --env=canary"
    },
    electrobun: {
        version: "2.0.2"
    }
}
