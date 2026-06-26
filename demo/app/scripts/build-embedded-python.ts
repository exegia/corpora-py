// scripts/build-embedded-python.ts
// Clean script to build the Python wheel and embed it into the ElectroBun resources.
//
// Run with:
//   bun scripts/build-embedded-python.ts
//
// This will:
// 1. Build the wheel from the monorepo root using uv
// 2. Bundle a standalone Python + the wheel into demo/app/resources/python
// 3. The resulting python binary can be used by python-bridge.ts
//
// The ElectroBun app (when not in DEV_PYTHON_BIN mode) will spawn this embedded Python.

import { $ } from "bun";
import { existsSync, mkdirSync } from "fs";
import { join, resolve } from "path";
import { parseArgs } from "util";

const { values } = parseArgs({
  args: Bun.argv.slice(2),
  options: {
    platform: { type: "string" },
    clean: { type: "boolean" },
  },
});

const REPO_ROOT = resolve(import.meta.dir, "../../..");
const DEMO_APP_DIR = resolve(import.meta.dir, "..");
const DIST_DIR = join(REPO_ROOT, "dist");
const RESOURCES_PYTHON = join(DEMO_APP_DIR, "resources/python");

console.log("==> Building embedded Python for ElectroBun demo");
console.log(`    Repo root: ${REPO_ROOT}`);
console.log(`    Target resources: ${RESOURCES_PYTHON}`);

if (values.clean) {
  console.log("==> Cleaning previous resources/python");
  await $`rm -rf ${RESOURCES_PYTHON}`.quiet().nothrow();
}

// 1. Build the wheel
console.log("\n==> Building wheel with uv...");
await $`cd ${REPO_ROOT} && uv build --wheel --out-dir ${DIST_DIR}`;

// 2. Find the wheel
const wheelFiles = (await $`ls ${DIST_DIR}/corpora_py-*.whl 2>/dev/null || ls ${DIST_DIR}/*.whl`.text()).trim().split("\n").filter(Boolean);
if (wheelFiles.length === 0) {
  console.error("No wheel found in dist/. Did uv build succeed?");
  process.exit(1);
}

const wheelPath = wheelFiles[0];
console.log(`    Found wheel: ${wheelPath}`);

// 3. Run the bundler (it will create resources/python)
console.log("\n==> Bundling standalone Python + wheel...");
const bundleScript = join(DEMO_APP_DIR, "scripts/bundle-python.ts");
const bundleArgs = [wheelPath];
if (values.platform) {
  bundleArgs.push("--platform", values.platform);
}

await $`cd ${DEMO_APP_DIR} && bun ${bundleScript} ${bundleArgs}`;

console.log("\n✅ Done!");
console.log(`   Embedded Python is at: ${RESOURCES_PYTHON}/bin/python3`);
console.log("\n   To use it locally (without Docker dev override):");
console.log("     unset DEV_PYTHON_BIN DEV_PYTHON_HOME");
console.log("     bun run dev     # or whatever launches the ElectroBun app");
console.log("\n   The python-bridge.ts will automatically use this embedded Python.");
