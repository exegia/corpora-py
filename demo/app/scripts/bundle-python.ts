// scripts/bundle-python.ts
// Run with: bun scripts/bundle-python.ts <path-to-wheel.whl> [--platform macos-arm64|macos-x64|linux-x64|windows-x64]

import { $ } from "bun";
import { existsSync, readFileSync, mkdirSync, writeFileSync } from "fs";
import { join } from "path";
import { parseArgs } from "util";

const PYTHON_VERSION = "3.13.14";
const STANDALONE_VERSION = "20260623";
const DEST_DIR = "resources/python";

const { values, positionals } = parseArgs({
  args: Bun.argv.slice(2),
  options: {
    platform: { type: "string" },
  },
  allowPositionals: true,
});

const wheelPath = positionals[0];
if (!wheelPath || !existsSync(wheelPath)) {
  console.error(`Usage: bun scripts/bundle-python.ts <path-to-wheel.whl> [--platform macos-arm64|macos-x64|linux-x64|windows-x64]`);
  process.exit(1);
}

// --- Detect platform ---
let platform = values.platform;
if (!platform) {
  const os = process.platform;
  const arch = process.arch;
  if (os === "darwin" && arch === "arm64") platform = "macos-arm64";
  else if (os === "darwin" && arch === "x64") platform = "macos-x64";
  else if (os === "linux" && arch === "x64") platform = "linux-x64";
  else {
    console.error(`Cannot auto-detect platform for ${os}-${arch}. Use --platform.`);
    process.exit(1);
  }
}

const PLATFORM_MAP: Record<string, { standalone: string; lib: string }> = {
  "macos-arm64": { standalone: "aarch64-apple-darwin", lib: "libpython3.13.dylib" },
  "macos-x64":   { standalone: "x86_64-apple-darwin",  lib: "libpython3.13.dylib" },
  "linux-x64":   { standalone: "x86_64-unknown-linux-gnu", lib: "libpython3.13.so" },
  "windows-x64": { standalone: "x86_64-pc-windows-msvc-shared", lib: "python313.dll" },
};

const platformInfo = PLATFORM_MAP[platform];
if (!platformInfo) {
  console.error(`Unknown platform: ${platform}`);
  process.exit(1);
}

const tarballName = `cpython-${PYTHON_VERSION}+${STANDALONE_VERSION}-${platformInfo.standalone}-install_only.tar.gz`;
const downloadUrl = `https://github.com/astral-sh/python-build-standalone/releases/download/${STANDALONE_VERSION}/${tarballName}`;

console.log(`==> Platform: ${platform}`);
console.log(`==> Python: ${PYTHON_VERSION}`);
console.log(`==> Wheel: ${wheelPath}`);

// --- Download standalone Python ---
const cacheDir = ".cache/python-standalone";
mkdirSync(cacheDir, { recursive: true });
const cachedTarball = join(cacheDir, tarballName);

if (!existsSync(cachedTarball)) {
  console.log("==> Downloading standalone Python...");
  await $`curl -L --progress-bar -o ${cachedTarball} ${downloadUrl}`;
} else {
  console.log(`==> Using cached download: ${cachedTarball}`);
}

// --- Extract ---
console.log("==> Extracting...");
await $`rm -rf ${DEST_DIR}`;
mkdirSync(DEST_DIR, { recursive: true });
await $`tar -xzf ${cachedTarball} -C ${DEST_DIR} --strip-components=1`;

// --- Install wheel with uv ---
console.log("==> Installing wheel with uv...");
await $`uv pip install --python ${DEST_DIR}/bin/python3 --no-cache ${wheelPath}`;

// --- Trim stdlib ---
console.log("==> Trimming stdlib...");
const pylib = `${DEST_DIR}/lib/python3.13`;

const removeItems = [
  "test", "unittest", "tkinter", "idlelib", "turtledemo", "turtle.py",
  "ensurepip", "lib2to3", "pydoc_data", "doctest.py", "_pydecimal.py",
  "pydoc.py", "mailbox.py", "imaplib.py", "nntplib.py", "poplib.py",
  "smtplib.py", "ftplib.py", "xmlrpc", "curses", "multiprocessing",
  "concurrent",
];

for (const item of removeItems) {
  const target = join(pylib, item);
  if (existsSync(target)) {
    await $`rm -rf ${target}`.quiet();
  }
}

await $`find ${DEST_DIR} -name "__pycache__" -type d -exec rm -rf {} +`.quiet().nothrow();
await $`find ${DEST_DIR} -name "*.pyc" -delete`.quiet().nothrow();
await $`rm -rf ${DEST_DIR}/share ${DEST_DIR}/man`.quiet().nothrow();
await $`rm -rf ${DEST_DIR}/lib/pkgconfig ${DEST_DIR}/include`.quiet().nothrow();
await $`find ${DEST_DIR}/lib -name "*.a" -delete`.quiet().nothrow();

// --- Report sizes ---
const total = (await $`du -sh ${DEST_DIR}`.text()).split("\t")[0];
const libSize = (await $`du -sh ${DEST_DIR}/lib/${platformInfo.lib}`.text().catch(() => "N/A")).split("\t")[0];
const stdlibSize = (await $`du -sh ${pylib}`.text()).split("\t")[0];
const siteSize = (await $`du -sh ${pylib}/site-packages`.text()).split("\t")[0];

console.log("");
console.log(`==> Done! Bundled Python at: ${DEST_DIR}/`);
console.log("");
console.log(`    Total:         ${total}`);
console.log(`    Shared lib:    ${libSize} (${platformInfo.lib})`);
console.log(`    Stdlib:        ${stdlibSize}`);
console.log(`    Site-packages: ${siteSize}`);
