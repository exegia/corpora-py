// scripts/clean.ts
// Clean all dev-generated and cache files in the ElectroBun demo app.
//
// Run with:
//   bun run clean
//   bun scripts/clean.ts
//
// This removes build artifacts, Vite output, generated Python runtime,
// caches, etc. These are all gitignored (see .gitignore).

import { $ } from "bun"
import { rm } from "fs/promises"
import { existsSync } from "fs"
import { resolve, join } from "path"

const ROOT = resolve(import.meta.dir, "..")

const DIRS_TO_REMOVE = [
  "build",
  "dist",
  "build/lib",
  "node_modules",
  ".cache",
  "artifacts"
]

async function removeDir(name: string) {
  const fullPath = join(ROOT, name)
  if (existsSync(fullPath)) {
    await rm(fullPath, { recursive: true, force: true })
    console.log(`  removed  ${name}`)
  }
}

async function main() {
  console.log("Cleaning demo dev artifacts...\n")

  console.log("Removing top-level generated directories...")
  for (const dir of DIRS_TO_REMOVE) {
    await removeDir(dir)
  }

  console.log("\nRemoving cache artifacts...")
  // ElectroBun cache (inside node_modules)
  const electrobunCache = join(ROOT, "node_modules/electrobun/.cache")
  if (existsSync(electrobunCache)) {
    await rm(electrobunCache, { recursive: true, force: true })
    console.log("  removed  node_modules/electrobun/.cache")
  }

  // Any leftover *.tsbuildinfo (TypeScript incremental builds)
  try {
    await $`find ${ROOT} -name "*.tsbuildinfo" -type f -delete 2>/dev/null`.quiet()
    console.log("  removed  *.tsbuildinfo files")
  } catch {
    // ignore if none or find not perfect
  }

  // Clean any other common temp/caches that might be left
  const extraGlobs = [
    "**/.temp",
    "**/tmp"
  ]
  for (const pattern of extraGlobs) {
    try {
      await $`find ${ROOT} -path "*/${pattern}" -type d -exec rm -rf {} + 2>/dev/null`.quiet()
    } catch {
    }
  }

  console.log("\nDone. Run `bun install` if you also want to refresh node_modules.")
}

main().catch((err) => {
  console.error("Clean failed:", err)
  process.exit(1)
})
