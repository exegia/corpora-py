"use client"

import { useEffect, useRef, useState } from "react"
import { cue } from "~/lib/cue"
import { buildStoredZip, type ZipFileInput } from "~/lib/uploads/build-zip"

interface RepoRef {
  owner: string
  repo: string
  branch: string
}

type TreeNode = { path: string; type: "blob" | "tree"; size?: number }

type Detection = {
  paths: string[]
  description: string
}

export type GithubRepoImportPhase =
  | { kind: "idle" }
  | { kind: "checking"; message: string }
  | { kind: "error"; message: string }

export type GithubRepoValidation =
  | { kind: "idle" }
  | { kind: "validating" }
  | { kind: "valid" }
  | { kind: "invalid"; message: string }

export interface UseGithubRepoImportOptions {
  onFile: (file: File) => void
}

const DOCUMENT_EXTENSIONS = [".epub", ".html", ".pdf", ".txt"]
const CONVERTIBLE_EXTENSIONS = [".tf", ".tei", ".xml", ...DOCUMENT_EXTENSIONS]
const MAX_CONTENT_BYTES = 100 * 1024 * 1024
const MAX_FILE_COUNT = 1000
const DOWNLOAD_BATCH = 8

const parseGithubUrl = (raw: string): RepoRef | null => {
  const trimmed = raw.trim()
  if (!trimmed) return null

  const withoutProtocol = trimmed
    .replace(/^(https?:\/\/)?(www\.)?/i, "")
    .replace(/^github\.com[/:]/i, "")

  if (/^[a-z0-9.-]+\.[a-z]{2,}\//i.test(withoutProtocol)) return null

  const segments = withoutProtocol.split("/").filter(Boolean)
  const [owner, repoRaw] = segments
  if (!owner || !repoRaw) return null

  const repo = repoRaw.replace(/\.git$/i, "")
  if (!/^[\w.-]+$/.test(owner) || !/^[\w.-]+$/.test(repo)) return null

  const branch = segments[2] === "tree" && segments[3] ? segments[3] : ""
  return { owner, repo, branch }
}

const dirOf = (path: string): string =>
  path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "."

const bestDirectory = (nodes: TreeNode[], extensions: string[]): string[] => {
  const byDir = new Map<string, string[]>()
  for (const node of nodes) {
    if (node.type !== "blob") continue
    const lower = node.path.toLowerCase()
    if (!extensions.some((extension) => lower.endsWith(extension))) continue

    const directory = dirOf(node.path)
    byDir.set(directory, [...(byDir.get(directory) ?? []), node.path])
  }

  const best = [...byDir.entries()].sort(
    (a, b) => b[1].length - a[1].length || b[0].localeCompare(a[0])
  )[0]
  return best?.[1] ?? []
}

const detectConvertibleContent = (nodes: TreeNode[]): Detection | null => {
  const textFabricFiles = bestDirectory(nodes, [".tf"])
  if (textFabricFiles.length > 0) {
    return {
      paths: textFabricFiles,
      description: `Text-Fabric dataset — ${textFabricFiles.length} .tf file${textFabricFiles.length === 1 ? "" : "s"} in ${dirOf(textFabricFiles[0]!)}/`
    }
  }

  const teiFiles = bestDirectory(nodes, [".tei", ".xml"])
  if (teiFiles.length > 0) {
    return {
      paths: teiFiles,
      description: `TEI/XML corpus — ${teiFiles.length} document${teiFiles.length === 1 ? "" : "s"} in ${dirOf(teiFiles[0]!)}/`
    }
  }

  const documents = nodes.filter(
    (node) =>
      node.type === "blob" &&
      DOCUMENT_EXTENSIONS.some((extension) =>
        node.path.toLowerCase().endsWith(extension)
      )
  )
  const largest = documents.sort((a, b) => (b.size ?? 0) - (a.size ?? 0))[0]
  return largest ? { paths: [largest.path], description: largest.path } : null
}

type RepoCheck =
  | { ok: true; info: { default_branch: string } }
  | { ok: false; message: string }

// Shared by the live validation (as-you-type) and the import flow itself, so
// both report the same failures for the same repo.
const checkRepository = async (ref: RepoRef): Promise<RepoCheck> => {
  const repoLabel = `${ref.owner}/${ref.repo}`
  try {
    const response = await fetch(
      `https://api.github.com/repos/${ref.owner}/${ref.repo}`
    )
    if (response.status === 404) {
      return {
        ok: false,
        message: `Repository ${repoLabel} was not found — it may not exist, or it's private. Only public repositories can be imported.`
      }
    }
    if (response.status === 403) {
      return {
        ok: false,
        message:
          "GitHub API rate limit reached for unauthenticated requests. Wait a few minutes and try again."
      }
    }
    if (!response.ok) {
      return {
        ok: false,
        message: `GitHub returned an unexpected error (HTTP ${response.status}).`
      }
    }
    return {
      ok: true,
      info: (await response.json()) as { default_branch: string }
    }
  } catch {
    return {
      ok: false,
      message:
        "Couldn't reach GitHub. Check your connection (or the repository URL) and try again."
    }
  }
}

// Debounce before hitting the GitHub API on keystrokes — unauthenticated
// requests are limited to 60/hour.
const VALIDATION_DEBOUNCE_MS = 600

export const useGithubRepoImport = ({ onFile }: UseGithubRepoImportOptions) => {
  const [url, setUrlState] = useState("")
  const [phase, setPhase] = useState<GithubRepoImportPhase>({ kind: "idle" })
  const [validation, setValidation] = useState<GithubRepoValidation>({
    kind: "idle"
  })
  const [validationAttempt, setValidationAttempt] = useState(0)
  // Guards against out-of-order responses: only the latest validation run may
  // publish its result.
  const validationSeq = useRef(0)
  const busy = phase.kind === "checking"

  const fail = (message: string) => {
    cue("repoInvalid")
    setPhase({ kind: "error", message })
  }

  const setUrl = (value: string) => {
    setUrlState(value)
    if (phase.kind === "error") setPhase({ kind: "idle" })
  }

  // Live validation: as soon as the input parses as a GitHub repo URL, show
  // the spinner and (after a debounce) ask GitHub whether the repo exists.
  useEffect(() => {
    const ref = parseGithubUrl(url)
    if (!ref) {
      validationSeq.current++
      setValidation({ kind: "idle" })
      return
    }

    const seq = ++validationSeq.current
    setValidation({ kind: "validating" })
    const timer = setTimeout(async () => {
      const result = await checkRepository(ref)
      if (validationSeq.current !== seq) return
      setValidation(
        result.ok
          ? { kind: "valid" }
          : { kind: "invalid", message: result.message }
      )
      cue(result.ok ? "repoValid" : "repoInvalid")
    }, VALIDATION_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [url, validationAttempt])

  const retryValidation = () => setValidationAttempt((n) => n + 1)

  const importRepository = async () => {
    const ref = parseGithubUrl(url)
    if (!ref) {
      fail(
        "That doesn't look like a GitHub repository URL. Expected something like https://github.com/owner/repo."
      )
      return
    }

    const repoLabel = `${ref.owner}/${ref.repo}`
    setPhase({ kind: "checking", message: `Checking ${repoLabel}…` })

    try {
      const check = await checkRepository(ref)
      if (!check.ok) {
        fail(check.message)
        return
      }

      const branch = ref.branch || check.info.default_branch
      setPhase({
        kind: "checking",
        message: `Scanning ${repoLabel}@${branch}…`
      })

      const treeResponse = await fetch(
        `https://api.github.com/repos/${ref.owner}/${ref.repo}/git/trees/${encodeURIComponent(branch)}?recursive=1`
      )
      if (treeResponse.status === 404) {
        fail(`Branch "${branch}" was not found in ${repoLabel}.`)
        return
      }
      if (!treeResponse.ok) {
        fail(`Couldn't read the repository tree (HTTP ${treeResponse.status}).`)
        return
      }

      const tree = (await treeResponse.json()) as {
        tree: TreeNode[]
        truncated: boolean
      }
      const found = detectConvertibleContent(tree.tree)
      if (!found) {
        fail(
          `${repoLabel} contains no convertible content — looked for Text-Fabric (.tf), TEI/XML, and document files (${CONVERTIBLE_EXTENSIONS.join(", ")})${tree.truncated ? ". Note: the repository tree was too large to scan completely" : ""}.`
        )
        return
      }
      if (found.paths.length > MAX_FILE_COUNT) {
        fail(
          `Found ${found.paths.length} files (${found.description}) — too many to import in the browser. Upload a ZIP of the relevant directory instead.`
        )
        return
      }

      const totalBytes = tree.tree
        .filter((node) => found.paths.includes(node.path))
        .reduce((sum, node) => sum + (node.size ?? 0), 0)
      if (totalBytes > MAX_CONTENT_BYTES) {
        fail(
          `The convertible content in ${repoLabel} is about ${Math.round(totalBytes / (1024 * 1024))} MB — too large to import in the browser. Upload a ZIP of the relevant directory instead.`
        )
        return
      }

      const downloaded: ZipFileInput[] = []
      for (let start = 0; start < found.paths.length; start += DOWNLOAD_BATCH) {
        setPhase({
          kind: "checking",
          message: `Found ${found.description}. Downloading ${Math.min(start + DOWNLOAD_BATCH, found.paths.length)}/${found.paths.length} files…`
        })
        const batch = found.paths.slice(start, start + DOWNLOAD_BATCH)
        const results = await Promise.all(
          batch.map(async (path) => {
            const response = await fetch(
              `https://raw.githubusercontent.com/${ref.owner}/${ref.repo}/${encodeURIComponent(branch)}/${path.split("/").map(encodeURIComponent).join("/")}`
            )
            if (!response.ok)
              throw new Error(`HTTP ${response.status} for ${path}`)

            return {
              name: path.split("/").pop()!,
              data: new Uint8Array(await response.arrayBuffer())
            }
          })
        )
        downloaded.push(...results)
      }

      const single = downloaded.length === 1 ? downloaded[0]! : null
      const file = single
        ? new File([single.data], single.name)
        : new File([buildStoredZip(downloaded)], `${ref.repo}.zip`, {
          type: "application/zip"
        })

      setPhase({ kind: "idle" })
      setUrlState("")
      onFile(file)
    } catch (error) {
      fail(
        error instanceof Error && !error.message.includes("Failed to fetch")
          ? `Import failed: ${error.message}`
          : "Couldn't reach GitHub. Check your connection (or the repository URL) and try again."
      )
    }
  }

  return {
    url,
    setUrl,
    phase,
    busy,
    validation,
    retryValidation,
    importRepository
  }
}
