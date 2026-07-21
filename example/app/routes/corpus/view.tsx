import { useCallback, useEffect, useState } from "react"
import { Form, useParams, useSearchParams } from "react-router"
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  Loader2,
  RefreshCw,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty"
import { Skeleton } from "~/components/ui/skeleton"
import {
  fetchContent,
  fetchIndex,
  type Passage,
  type PickerOption,
  pickerOptions,
} from "~/lib/corpus-detail"
import { cn } from "~/lib/utils"
import { Input } from "@base-ui/react"
import {
  ChatPanel,
  CorpusBlock,
  SplitWorkspace,
  WorkspaceProvider,
} from "~/components/workspace"

export function meta() {
  return [{ title: "Corpus viewer · Corpora" }]
}

/** Passages fetched per content request. */
const PAGE_SIZE = 25

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error)

type ContentState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready"
      passages: Passage[]
      total: number
      query: string
      nextOffset: number | null
      format: string
      ref: string | null
    }

export default function CorpusView() {
  const { id } = useParams()
  const corpusId = id ?? ""
  const [searchParams, setSearchParams] = useSearchParams()
  const ref = searchParams.get("ref") ?? ""

  const [options, setOptions] = useState<PickerOption[]>([])
  const [state, setState] = useState<ContentState>({ status: "loading" })
  const [query, setQuery] = useState("")
  const [loadingMore, setLoadingMore] = useState(false)

  // Section picker data — best-effort; a missing index just hides the picker.
  useEffect(() => {
    if (!corpusId) return
    let active = true
    void fetchIndex(corpusId)
      .then((index) => {
        if (active) setOptions(pickerOptions(index.sections))
      })
      .catch(() => {
        if (active) setOptions([])
      })
    return () => {
      active = false
    }
  }, [corpusId])

  const load = useCallback(() => {
    if (!corpusId) return
    setState({ status: "loading" })
    void fetchContent(corpusId, {
      ref: ref || null,
      offset: 0,
      limit: PAGE_SIZE,
    })
      .then((res) =>
        setState({
          status: "ready",
          passages: res.passages,
          total: res.total,
          nextOffset: res.next_offset,
          format: res.format,
          ref: res.ref,
          query: "",
        })
      )
      .catch((error) =>
        setState({ status: "error", message: errorMessage(error) })
      )
  }, [corpusId, ref])

  useEffect(() => {
    load()
  }, [load])

  const loadMore = () => {
    if (state.status !== "ready" || state.nextOffset == null) return
    setLoadingMore(true)
    void fetchContent(corpusId, {
      ref: ref || null,
      offset: state.nextOffset,
      limit: PAGE_SIZE,
    })
      .then((res) =>
        setState((prev) =>
          prev.status === "ready"
            ? {
                ...prev,
                passages: [...prev.passages, ...res.passages],
                total: res.total,
                nextOffset: res.next_offset,
              }
            : prev
        )
      )
      .catch((error) =>
        setState({ status: "error", message: errorMessage(error) })
      )
      .finally(() => setLoadingMore(false))
  }

  const onPickRef = (value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set("ref", value)
    else next.delete("ref")
    setSearchParams(next)
  }

  const loaded = state.status === "ready" ? state.passages.length : 0
  const total = state.status === "ready" ? state.total : 0

  // Left pane of the split workspace — the existing reader, unchanged apart
  // from passages now rendering as selectable `CorpusBlock`s.
  const reader = (
    <div className="flex w-full flex-col gap-4">
      {/* Search uses Form method="get" so the query lives in the URL. */}
      <Form method="get" className="w-full">
        <label htmlFor="q" className="sr-only">{`Search ${id}`}</label>
        <Input
          aria-label="placeholder="
          id="q"
          name="q"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${id}…`}
        />
      </Form>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <CardTitle>Reader</CardTitle>
            {state.status === "ready" && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {loaded.toLocaleString()} of {total.toLocaleString()} passages
              </span>
            )}
          </div>

          {options.length > 0 && (
            <div className="mt-2 flex flex-col gap-1.5">
              <label
                htmlFor="section-picker"
                className="text-sm font-medium text-neutral-700 dark:text-neutral-300"
              >
                Section
              </label>
              <div className="relative max-w-md">
                <select
                  id="section-picker"
                  value={ref}
                  onChange={(event) => onPickRef(event.target.value)}
                  className={cn(
                    "h-9 w-full appearance-none rounded-md border border-input bg-transparent px-2.5 pr-8 text-sm shadow-xs transition-[color,box-shadow] outline-none",
                    "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                  )}
                >
                  <option value="">Whole corpus (from start)</option>
                  {options.map((option) => (
                    <option key={option.ref} value={option.ref}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
                  aria-hidden="true"
                />
              </div>
            </div>
          )}
        </CardHeader>

        <CardContent className="flex flex-col gap-4">
          {ref && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>Showing</span>
              <Badge variant="secondary" className="font-mono">
                {ref}
              </Badge>
            </div>
          )}

          {state.status === "loading" && (
            <div className="flex flex-col gap-2" aria-label="Loading passages">
              {[0, 1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="flex flex-col gap-2 rounded-md border p-3"
                >
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-4/5" />
                </div>
              ))}
            </div>
          )}

          {state.status === "error" && (
            <div className="flex flex-col gap-3">
              <Alert variant="destructive" role="alert">
                <AlertTriangle className="size-4" aria-hidden="true" />
                <AlertTitle>Couldn’t load passages</AlertTitle>
                <AlertDescription>
                  {state.message} Check that the conversion API is running and
                  the reference is valid, then try again.
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

          {state.status === "ready" && state.passages.length === 0 && (
            <Empty className="border-2 border-dashed">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BookOpen className="size-6" aria-hidden="true" />
                </EmptyMedia>
                <EmptyTitle>No passages here</EmptyTitle>
                <EmptyDescription>
                  {ref
                    ? "This reference returned no text. Try another section."
                    : "This corpus returned no readable passages."}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {state.status === "ready" && state.passages.length > 0 && (
            <>
              <ol className="flex flex-col gap-2" aria-label="Passages">
                {state.passages.map((passage, index) => (
                  <CorpusBlock
                    key={`${passage.ref}-${index}`}
                    passage={passage}
                    blockKey={`${passage.ref}#${index}`}
                  />
                ))}
              </ol>

              {state.nextOffset != null && (
                <div className="flex justify-center">
                  <Button
                    variant="outline"
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="gap-1.5"
                    data-cuelume-press
                    data-cuelume-release
                  >
                    {loadingMore ? (
                      <Loader2
                        className="size-4 animate-spin motion-reduce:animate-none"
                        aria-hidden="true"
                      />
                    ) : (
                      <ChevronDown className="size-4" aria-hidden="true" />
                    )}
                    {loadingMore ? "Loading…" : "Load more"}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )

  // Split-screen workspace: reader on the left, mock AI chat on the right.
  // The provider wires block selection/focus, attachments, and composer
  // inserts between the two panes (UI-only — no LLM calls or persistence).
  return (
    <WorkspaceProvider corpusId={corpusId}>
      <SplitWorkspace reader={reader} chat={<ChatPanel />} />
    </WorkspaceProvider>
  )
}
