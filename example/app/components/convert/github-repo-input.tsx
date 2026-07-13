"use client"

import { useState } from "react"
import { CircleAlert, LoaderCircle } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Button } from "~/components/ui/button"
import { Input } from "~/components/ui/input"
import { buildStoredZip, type ZipFileInput } from "~/lib/uploads/build-zip"
import { cn } from "~/lib/utils"
import { GithubIcon } from "~/components/icons/icon-github"

/**
 * Paste-a-GitHub-URL alternative to the file dropzone. Before anything is
 *  downloaded, the repository is validated against the GitHub REST API:
 *
 * 1. `GET /repos/{owner}/{repo}` -- a 404 (repo doesn't exist, or is
 *    private and thus invisible to unauthenticated requests) stops here
 *    with an inline error, as does a 403 rate-limit response.
 * 2. `GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1` -- the
 *    whole tree in one call, scanned for content the conversion service
 *    can actually handle (`.tf` Text-Fabric files, TEI/XML documents, or
 *    a single convertible document). A repo with none of these is
 *    rejected before wasting a zipball download.
 *
 * Only then are the detected files fetched from raw.githubusercontent.com
 * (GitHub's zipball endpoint lives on codeload, which blocks cross-origin
 * requests) and packaged into a stored ZIP handed to `onFile` as a regular
 * `File`, so the page routes it through the same `inspectZip` -> upload
 * flow as a dropped ZIP.
 */

interface RepoRef {
  owner: string
  repo: string
  /** Branch from a /tree/<branch> URL; empty means use the default branch. */
  branch: string
}

/**
 * Accepts the usual shapes people paste: with/without protocol or `www.`,
 * a bare `owner/repo`, a `.git` suffix, or a deep `/tree/<branch>/...` link.
 */
const parseGithubUrl = (raw: string): RepoRef | null => {
  const trimmed = raw.trim()
  if (!trimmed) return null
  const withoutProtocol = trimmed
    .replace(/^(https?:\/\/)?(www\.)?/i, "")
    .replace(/^github\.com[/:]/i, "")
  // Reject non-GitHub hosts (e.g. gitlab.com/...) but allow bare owner/repo.
  if (/^[a-z0-9.-]+\.[a-z]{2,}\//i.test(withoutProtocol)) return null
  const segments = withoutProtocol.split("/").filter(Boolean)
  const [owner, repoRaw] = segments
  if (!owner || !repoRaw) return null
  const repo = repoRaw.replace(/\.git$/i, "")
  if (!/^[\w.-]+$/.test(owner) || !/^[\w.-]+$/.test(repo)) return null
  const branch = segments[2] === "tree" && segments[3] ? segments[3] : ""
  return { owner, repo, branch }
}

type TreeNode = { path: string; type: "blob" | "tree"; size?: number }

const DOCUMENT_EXTENSIONS = [".epub", ".html", ".pdf", ".txt"]
const CONVERTIBLE_EXTENSIONS = [".tf", ".tei", ".xml", ...DOCUMENT_EXTENSIONS]

type Detection = {
  /** Repo-relative blob paths to download, all from one directory. */
  paths: string[]
  /** Human description for the status line, e.g. "Text-Fabric dataset…". */
  description: string
}

const dirOf = (path: string): string =>
  path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "."

/**
 * Blobs with a matching extension in the single best directory: the one
 * with the most matches, ties broken by descending name so a versioned
 * layout like tf/0.1 vs tf/0.2 picks the newest.
 */
const bestDirectory = (nodes: TreeNode[], extensions: string[]): string[] => {
  const byDir = new Map<string, string[]>()
  for (const node of nodes) {
    if (node.type !== "blob") continue
    const lower = node.path.toLowerCase()
    if (!extensions.some((ext) => lower.endsWith(ext))) continue
    const dir = dirOf(node.path)
    byDir.set(dir, [...(byDir.get(dir) ?? []), node.path])
  }
  const best = [...byDir.entries()].sort(
    (a, b) => b[1].length - a[1].length || b[0].localeCompare(a[0])
  )[0]
  return best?.[1] ?? []
}

/**
 * What in this repo can the conversion service work with? Preference
 * order mirrors inspect-zip.ts: a Text-Fabric dataset beats TEI/XML
 * documents beats a lone convertible document (largest one wins).
 * Null when there is nothing usable.
 */
const detectConvertibleContent = (nodes: TreeNode[]): Detection | null => {
  const tf = bestDirectory(nodes, [".tf"])
  if (tf.length > 0)
    return {
      paths: tf,
      description: `Text-Fabric dataset — ${tf.length} .tf file${tf.length === 1 ? "" : "s"} in ${dirOf(tf[0]!)}/`
    }
  const tei = bestDirectory(nodes, [".tei", ".xml"])
  if (tei.length > 0)
    return {
      paths: tei,
      description: `TEI/XML corpus — ${tei.length} document${tei.length === 1 ? "" : "s"} in ${dirOf(tei[0]!)}/`
    }
  const documents = nodes.filter(
    (node) =>
      node.type === "blob" &&
      DOCUMENT_EXTENSIONS.some((ext) => node.path.toLowerCase().endsWith(ext))
  )
  const largest = documents.sort((a, b) => (b.size ?? 0) - (a.size ?? 0))[0]
  if (largest) return { paths: [largest.path], description: largest.path }
  return null
}

// Files come down one by one from raw.githubusercontent.com and are held
// in memory to build the upload archive -- refuse anything bigger.
const MAX_CONTENT_BYTES = 100 * 1024 * 1024
const MAX_FILE_COUNT = 1000
const DOWNLOAD_BATCH = 8

type Phase =
  | { kind: "idle" }
  | { kind: "checking"; message: string }
  | { kind: "error"; message: string }

interface GithubRepoInputProps {
  disabled?: boolean
  /** Receives the repo zipball as a File; routed like a dropped ZIP. */
  onFile: (file: File) => void
  className?: string
}

export function GithubRepoInput({
                                  disabled = false,
                                  onFile,
                                  className
                                }: GithubRepoInputProps) {
  const [url, setUrl] = useState("")
  const [phase, setPhase] = useState<Phase>({ kind: "idle" })
  const busy = phase.kind === "checking"

  const fail = (message: string) => setPhase({ kind: "error", message })

  const handleImport = async () => {
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
      const repoResponse = await fetch(
        `https://api.github.com/repos/${ref.owner}/${ref.repo}`
      )
      if (repoResponse.status === 404) {
        fail(
          `Repository ${repoLabel} was not found — it may not exist, or it's private. Only public repositories can be imported.`
        )
        return
      }
      if (repoResponse.status === 403) {
        fail(
          "GitHub API rate limit reached for unauthenticated requests. Wait a few minutes and try again."
        )
        return
      }
      if (!repoResponse.ok) {
        fail(`GitHub returned an unexpected error (HTTP ${repoResponse.status}).`)
        return
      }
      const repoInfo = (await repoResponse.json()) as {
        default_branch: string
      }

      const branch = ref.branch || repoInfo.default_branch
      setPhase({ kind: "checking", message: `Scanning ${repoLabel}@${branch}…` })
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

      // codeload.github.com (the zipball host) doesn't allow cross-origin
      // requests, so the archive is assembled here instead: each detected
      // file comes from raw.githubusercontent.com and lands in a stored ZIP
      // that flows through the same inspect -> upload path as a dropped one.
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

      // A single document skips the ZIP wrapper and takes the normal
      // one-file conversion path directly.
      const single = downloaded.length === 1 ? downloaded[0]! : null
      const file = single
        ? new File([single.data], single.name)
        : new File([buildStoredZip(downloaded)], `${ref.repo}.zip`, {
          type: "application/zip"
        })
      setPhase({ kind: "idle" })
      setUrl("")
      onFile(file)
    } catch (error) {
      fail(
        error instanceof Error && !error.message.includes("Failed to fetch")
          ? `Import failed: ${error.message}`
          : "Couldn't reach GitHub. Check your connection (or the repository URL) and try again."
      )
    }
  }

  return (
    <div className={cn("flex w-full flex-col gap-3", className)}>
      <form
        className="flex items-center gap-2 group"
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy) void handleImport()
        }}
      >
        <div
          className="relative flex flex-1 items-stretch outline-2 rounded-full bg-background outline-transparent overflow-hidden focus-within:outline-input pr-2">
          <div
            className="flex flex-1 items-center pointer-events-none gap-1 bg-muted px-2 border-r border-border/50">
            <GithubIcon
              className="fill-foreground w-5 h-5"
              aria-hidden="true"
            />
            <span className="text-sm text-muted-foreground">https://github.com</span>
          </div>

          <Input
            type="url"
            value={url}
            placeholder="@owner/repository"
            aria-label="GitHub repository URL"
            aria-invalid={phase.kind === "error" || undefined}
            disabled={disabled || busy}
            className={cn("border-none bg-transparent! focus:ring-0! focus:outline-none", className)}
            onChange={(event) => {
              setUrl(event.target.value)
              if (phase.kind === "error") setPhase({ kind: "idle" })
            }}
          />
        </div>
        <Button
          type="submit"
          size="sm"
          className="cursor-pointer rounded-full"
          disabled={disabled || busy || !url.trim()}
        >
          {busy && (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          )}
          Import
        </Button>
      </form>

      {phase.kind === "checking" && (
        <p className="text-xs text-muted-foreground" role="status">
          {phase.message}
        </p>
      )}

      {phase.kind === "error" && (
        <Alert variant="destructive" role="alert">
          <CircleAlert className="size-4" aria-hidden="true" />
          <AlertTitle>Can't import repository</AlertTitle>
          <AlertDescription>
            <p>{phase.message}</p>
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
