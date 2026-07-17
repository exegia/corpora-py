#!/usr/bin/env bun

import { existsSync } from "node:fs"
import { $ } from "bun"

const distDir = "dist"

if (existsSync(distDir)) {
  console.log(`"${distDir}" already exists — skipping.`)
  process.exit(0)
}

console.log(`"${distDir}" not found — running: 'bun run vite:build...`)

const { exitCode } = await $`vite build`.nothrow()
if (exitCode !== 0) process.exit(1)

if (exitCode === 0) {
  console.log("⚡ Vite HMR server starting...")
  const { exitCode: devExitCode } = await $`vite dev`.nothrow()
  process.exit(devExitCode)
}
