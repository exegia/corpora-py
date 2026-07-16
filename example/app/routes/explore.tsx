import { useEffect, useMemo, useState } from "react"
import { type MetaDescriptor, useNavigate } from "react-router"
import {
  Check,
  Download,
  ExternalLink,
  FileSpreadsheet,
  RefreshCw,
  Search,
  SearchX,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { HuggingFaceIcon } from "~/components/icons/icon-hugging-face"
import { FileTypeIcon } from "~/components/convert/file-icon"
import { Badge } from "~/components/ui/badge"
import { Button, buttonVariants } from "~/components/ui/button"
import { Card, CardContent } from "~/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty"
import { Input } from "~/components/ui/input"
import { Skeleton } from "~/components/ui/skeleton"
import { formatBytes } from "~/lib/hooks/use-file-upload"
import { API_URL } from "~/lib/types/socket"
import { cn } from "~/lib/utils"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Explore | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" },
  ]
}

/** One archive in the Hub storage repo — `GET /storage` response item
 * (`StoredCorpusResponse` in `admin.services.storage_api`). */
type StoredCorpus = {
  filename: string
  size_bytes: number | null
  repo_id: string
  url: string
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; corpora: StoredCorpus[] }

/** "athanasius-on-the-Incarnation.corpus" → "athanasius-on-the-Incarnation" */
const displayName = (filename: string): string =>
  filename.replace(/\.corpus$/i, "")

const fetchStoredCorpora = async (): Promise<LoadState> => {
  try {
    const response = await fetch(`${API_URL}/storage`)
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string
      }
      throw new Error(body.detail ?? `Request failed (${response.status})`)
    }
    const corpora = (await response.json()) as StoredCorpus[]
    return { status: "ready", corpora }
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : String(error),
    }
  }
}

export default function Explore() {
  const navigate = useNavigate()
  const [state, setState] = useState<LoadState>({ status: "loading" })
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState<string | null>(null)

  const load = () => {
    setState({ status: "loading" })
    void fetchStoredCorpora().then(setState)
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount
  useEffect(load, [])

  const corpora = state.status === "ready" ? state.corpora : []
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return corpora
    return corpora.filter(
      (corpus) =>
        corpus.filename.toLowerCase().includes(needle) ||
        corpus.repo_id.toLowerCase().includes(needle)
    )
  }, [corpora, query])

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">
          Explore{" "}
          <Badge variant="secondary" className="py-1.5 text-xl">
            .corpus
          </Badge>
        </h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Browse, search, and download the Context-Fabric <code>.corpus</code>{" "}
          archives published to the Hugging Face Hub.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-48 flex-1">
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search corpora…"
                aria-label="Search corpora"
                className="pl-9"
              />
            </div>
            {state.status === "ready" && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {filtered.length} of {corpora.length}{" "}
                {corpora.length === 1 ? "corpus" : "corpora"}
              </span>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={load}
              disabled={state.status === "loading"}
              aria-label="Refresh list"
              title="Refresh list"
              data-cuelume-press
              data-cuelume-release
            >
              <RefreshCw
                className={cn(
                  "size-4",
                  state.status === "loading" &&
                    "animate-spin motion-reduce:animate-none"
                )}
                aria-hidden="true"
              />
            </Button>
          </div>

          {state.status === "loading" && (
            <div className="flex flex-col gap-2" aria-label="Loading corpora">
              {[0, 1, 2].map((index) => (
                <div
                  key={index}
                  className="flex items-center gap-3 rounded-lg border-2 border-border p-3"
                >
                  <Skeleton className="size-10 rounded-lg" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {state.status === "error" && (
            <div className="flex flex-col gap-3">
              <Alert variant="destructive" role="alert">
                <SearchX className="size-4" aria-hidden="true" />
                <AlertTitle>Couldn’t load the corpus list</AlertTitle>
                <AlertDescription>
                  {state.message} Check that the conversion API is running and
                  Hub storage is configured, then try again.
                </AlertDescription>
              </Alert>
              <div>
                <Button
                  onClick={load}
                  className="gap-1.5"
                  data-cuelume-press
                  data-cuelume-release
                >
                  <RefreshCw className="size-4" aria-hidden="true" />
                  Try again
                </Button>
              </div>
            </div>
          )}

          {state.status === "ready" && corpora.length === 0 && (
            <Empty className="border-2 border-dashed">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <HuggingFaceIcon className="size-6" />
                </EmptyMedia>
                <EmptyTitle>No corpora published yet</EmptyTitle>
                <EmptyDescription>
                  Convert a document and use “Publish to Hugging Face” to make
                  it available here.
                </EmptyDescription>
              </EmptyHeader>
              <Button
                onClick={() => navigate("/corpus/convert")}
                className="gap-1.5"
                data-cuelume-press
                data-cuelume-release
              >
                <FileSpreadsheet className="size-4" aria-hidden="true" />
                Convert a document
              </Button>
            </Empty>
          )}

          {state.status === "ready" &&
            corpora.length > 0 &&
            filtered.length === 0 && (
              <Empty className="border-2 border-dashed">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <SearchX className="size-6" aria-hidden="true" />
                  </EmptyMedia>
                  <EmptyTitle>No corpora match “{query.trim()}”</EmptyTitle>
                  <EmptyDescription>
                    Try a different name, or clear the search to see all{" "}
                    {corpora.length}{" "}
                    {corpora.length === 1 ? "corpus" : "corpora"}.
                  </EmptyDescription>
                </EmptyHeader>
                <Button
                  variant="outline"
                  onClick={() => setQuery("")}
                  data-cuelume-press
                  data-cuelume-release
                >
                  Clear search
                </Button>
              </Empty>
            )}

          {state.status === "ready" && filtered.length > 0 && (
            <ul className="flex flex-col gap-2" aria-label="Published corpora">
              {filtered.map((corpus) => {
                const isSelected = selected === corpus.filename
                return (
                  <li key={corpus.filename}>
                    {/* The row is a div (not a button) so the action links
                        inside the selected row stay valid interactive
                        children; Enter/Space keep it keyboard-selectable. */}
                    <div
                      role="button"
                      tabIndex={0}
                      aria-pressed={isSelected}
                      onClick={() =>
                        setSelected(isSelected ? null : corpus.filename)
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault()
                          setSelected(isSelected ? null : corpus.filename)
                        }
                      }}
                      className={cn(
                        "flex cursor-pointer flex-col gap-3 rounded-lg border-2 bg-background p-3 transition-colors",
                        "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                        isSelected
                          ? "border-amber-400 dark:border-amber-500"
                          : "border-border hover:bg-muted/50"
                      )}
                    >
                      <div className="flex items-center gap-3">
                        <FileTypeIcon
                          filename={corpus.filename}
                          className="size-10 rounded-lg"
                          iconClassName="size-5"
                        />
                        <div className="min-w-0 flex-1">
                          <p
                            className="truncate text-sm font-medium"
                            title={corpus.filename}
                          >
                            {displayName(corpus.filename)}
                          </p>
                          <p className="truncate text-xs text-muted-foreground">
                            {corpus.size_bytes != null
                              ? `${formatBytes(corpus.size_bytes)} · `
                              : ""}
                            {corpus.repo_id}
                          </p>
                        </div>
                        {isSelected && (
                          <Check
                            className="size-4 shrink-0 text-amber-600 dark:text-amber-400"
                            aria-hidden="true"
                          />
                        )}
                      </div>

                      {isSelected && (
                        <div
                          className="flex animate-in flex-wrap items-center gap-2 duration-200 fade-in motion-reduce:animate-none"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <a
                            href={`${API_URL}/storage/${encodeURIComponent(corpus.filename)}/download`}
                            download={corpus.filename}
                            className={cn(buttonVariants(), "gap-1.5")}
                            data-cuelume-press
                            data-cuelume-release
                          >
                            <Download className="size-4" aria-hidden="true" />
                            Download
                          </a>
                          <a
                            href={corpus.url}
                            target="_blank"
                            rel="noreferrer"
                            className={cn(
                              buttonVariants({ variant: "outline" }),
                              "gap-2"
                            )}
                            data-cuelume-press
                            data-cuelume-release
                          >
                            <HuggingFaceIcon className="size-4" />
                            Open on Hugging Face
                            <ExternalLink
                              className="size-3.5 text-muted-foreground"
                              aria-hidden="true"
                            />
                          </a>
                        </div>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
