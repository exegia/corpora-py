import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
  AlertTriangle,
  BookOpen,
  ChevronRight,
  Layers,
  Pencil,
  RefreshCw,
  Save,
  X,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "~/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty"
import { Input } from "~/components/ui/input"
import { Skeleton } from "~/components/ui/skeleton"
import { Textarea } from "~/components/ui/textarea"
import {
  buildManifestPatch,
  type CorpusIndex,
  EDITABLE_MANIFEST_FIELDS,
  type EditableManifestField,
  fetchIndex,
  fetchManifest,
  type Manifest,
  manifestFieldLabel,
  patchManifest,
} from "~/lib/corpus-detail"
import { useCapabilities } from "~/lib/capabilities"
import { cn } from "~/lib/utils"

export function meta() {
  return [{ title: "Corpus detail · Corpora" }]
}

type ManifestState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; manifest: Manifest }

type IndexState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; index: CorpusIndex }

type Draft = Record<EditableManifestField, string>

const emptyDraft = (): Draft =>
  EDITABLE_MANIFEST_FIELDS.reduce((draft, field) => {
    draft[field] = ""
    return draft
  }, {} as Draft)

const draftFromManifest = (manifest: Manifest): Draft =>
  EDITABLE_MANIFEST_FIELDS.reduce((draft, field) => {
    const value = manifest[field]
    draft[field] = value == null ? "" : String(value)
    return draft
  }, {} as Draft)

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : String(error)

export default function CorpusDetail() {
  const { id } = useParams()
  const corpusId = id ?? ""
  const navigate = useNavigate()

  const [manifestState, setManifestState] = useState<ManifestState>({
    status: "loading",
  })
  const [indexState, setIndexState] = useState<IndexState>({
    status: "loading",
  })

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const loadManifest = () => {
    setManifestState({ status: "loading" })
    void fetchManifest(corpusId)
      .then((manifest) => setManifestState({ status: "ready", manifest }))
      .catch((error) =>
        setManifestState({ status: "error", message: errorMessage(error) })
      )
  }

  const loadIndex = () => {
    setIndexState({ status: "loading" })
    void fetchIndex(corpusId)
      .then((index) => setIndexState({ status: "ready", index }))
      .catch((error) =>
        setIndexState({ status: "error", message: errorMessage(error) })
      )
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on id change
  useEffect(() => {
    if (!corpusId) return
    setEditing(false)
    setSaveError(null)
    loadManifest()
    loadIndex()
  }, [corpusId])

  const beginEdit = () => {
    if (manifestState.status !== "ready") return
    setDraft(draftFromManifest(manifestState.manifest))
    setSaveError(null)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setSaveError(null)
  }

  const save = () => {
    if (manifestState.status !== "ready") return
    const patch = buildManifestPatch(manifestState.manifest, draft)
    setSaving(true)
    setSaveError(null)
    void patchManifest(corpusId, patch)
      .then((manifest) => {
        setManifestState({ status: "ready", manifest })
        setEditing(false)
      })
      .catch((error) => setSaveError(errorMessage(error)))
      .finally(() => setSaving(false))
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <MetadataCard
        state={manifestState}
        editing={editing}
        draft={draft}
        saving={saving}
        saveError={saveError}
        onDraftChange={(field, value) =>
          setDraft((prev) => ({ ...prev, [field]: value }))
        }
        onEdit={beginEdit}
        onCancel={cancelEdit}
        onSave={save}
        onRetry={loadManifest}
      />

      <IndexCard
        corpusId={corpusId}
        state={indexState}
        onRetry={loadIndex}
        onOpenViewer={(ref) =>
          navigate(
            `/corpus/${encodeURIComponent(corpusId)}/view${
              ref ? `?ref=${encodeURIComponent(ref)}` : ""
            }`
          )
        }
      />
    </div>
  )
}

// ── Metadata card ───────────────────────────────────────────────────────────

const READONLY_ROWS: { label: string; key: keyof Manifest }[] = [
  { label: "Format", key: "format" },
  { label: "Format version", key: "format_version" },
  { label: "Identifier", key: "uid" },
  { label: "Dataset", key: "datasetId" },
]

function MetadataCard({
  state,
  editing,
  draft,
  saving,
  saveError,
  onDraftChange,
  onEdit,
  onCancel,
  onSave,
  onRetry,
}: {
  state: ManifestState
  editing: boolean
  draft: Draft
  saving: boolean
  saveError: string | null
  onDraftChange: (field: EditableManifestField, value: string) => void
  onEdit: () => void
  onCancel: () => void
  onSave: () => void
  onRetry: () => void
}) {
  const manifest = state.status === "ready" ? state.manifest : null
  // `PATCH /storage/{id}/manifest` re-uploads the archive to the Hub, so a
  // read-only deployment refuses it -- offer "Edit" only where it can work.
  const canEdit = useCapabilities()?.hubWritable === true

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>Metadata</CardTitle>
            <CardDescription>
              Descriptive fields stored in the corpus manifest.
            </CardDescription>
          </div>
          {state.status === "ready" && !editing && canEdit && (
            <Button
              variant="outline"
              size="sm"
              onClick={onEdit}
              className="gap-1.5"
              data-cuelume-press
              data-cuelume-release
            >
              <Pencil className="size-4" aria-hidden="true" />
              Edit
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {state.status === "loading" && (
          <div className="flex flex-col gap-3" aria-label="Loading metadata">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ))}
          </div>
        )}

        {state.status === "error" && (
          <div className="flex flex-col gap-3">
            <Alert variant="destructive" role="alert">
              <AlertTriangle className="size-4" aria-hidden="true" />
              <AlertTitle>Couldn’t load the manifest</AlertTitle>
              <AlertDescription>
                {state.message} Check that the conversion API is running and Hub
                storage is configured, then try again.
              </AlertDescription>
            </Alert>
            <div>
              <Button
                onClick={onRetry}
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

        {manifest && !editing && (
          <dl className="divide-y rounded-md border">
            {EDITABLE_MANIFEST_FIELDS.map((field) => (
              <MetaRow
                key={field}
                label={manifestFieldLabel(field)}
                value={manifest[field] as string | undefined}
                wide={field === "description"}
              />
            ))}
            {READONLY_ROWS.map((row) => (
              <MetaRow
                key={row.key as string}
                label={row.label}
                value={manifest[row.key] as string | undefined}
              />
            ))}
          </dl>
        )}

        {manifest && editing && (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault()
              onSave()
            }}
          >
            {EDITABLE_MANIFEST_FIELDS.map((field) => {
              const label = manifestFieldLabel(field)
              const inputId = `manifest-${field}`
              return (
                <div key={field} className="flex flex-col gap-1.5">
                  <label
                    htmlFor={inputId}
                    className="text-sm font-medium text-neutral-700 dark:text-neutral-300"
                  >
                    {label}
                  </label>
                  {field === "description" ? (
                    <Textarea
                      id={inputId}
                      value={draft[field]}
                      onChange={(event) =>
                        onDraftChange(field, event.target.value)
                      }
                      disabled={saving}
                      rows={3}
                    />
                  ) : (
                    <Input
                      id={inputId}
                      value={draft[field]}
                      onChange={(event) =>
                        onDraftChange(field, event.target.value)
                      }
                      disabled={saving}
                    />
                  )}
                </div>
              )
            })}

            {saveError && (
              <Alert variant="destructive" role="alert">
                <AlertTriangle className="size-4" aria-hidden="true" />
                <AlertTitle>Couldn’t save changes</AlertTitle>
                <AlertDescription>{saveError}</AlertDescription>
              </Alert>
            )}

            <div className="flex items-center gap-2">
              <Button
                type="submit"
                disabled={saving}
                className="gap-1.5"
                data-cuelume-press
                data-cuelume-release
              >
                <Save
                  className={cn(
                    "size-4",
                    saving && "animate-spin motion-reduce:animate-none"
                  )}
                  aria-hidden="true"
                />
                {saving ? "Saving…" : "Save changes"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={onCancel}
                disabled={saving}
                className="gap-1.5"
                data-cuelume-press
                data-cuelume-release
              >
                <X className="size-4" aria-hidden="true" />
                Cancel
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  )
}

function MetaRow({
  label,
  value,
  wide,
}: {
  label: string
  value: string | undefined | null
  wide?: boolean
}) {
  const display = value == null || value === "" ? "—" : String(value)
  return (
    <div className="grid grid-cols-3 gap-2 px-4 py-2.5">
      <dt className="col-span-1 text-sm text-neutral-500 dark:text-neutral-400">
        {label}
      </dt>
      <dd
        className={cn(
          "col-span-2 text-sm",
          wide && "whitespace-pre-wrap",
          display === "—" && "text-neutral-400 dark:text-neutral-500"
        )}
      >
        {display}
      </dd>
    </div>
  )
}

// ── Index card ──────────────────────────────────────────────────────────────

function IndexCard({
  corpusId,
  state,
  onRetry,
  onOpenViewer,
}: {
  corpusId: string
  state: IndexState
  onRetry: () => void
  onOpenViewer: (ref: string) => void
}) {
  const sections = state.status === "ready" ? state.index.sections : null
  const nodeTypes = state.status === "ready" ? state.index.node_types : []
  const hasItems = !!sections && sections.items.length > 0

  return (
    <Card>
      <CardHeader>
        <CardTitle>Index</CardTitle>
        <CardDescription>
          Section structure of the corpus. Open any entry to read it.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {state.status === "loading" && (
          <div className="flex flex-col gap-2" aria-label="Loading index">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="flex items-center gap-3 rounded-lg border-2 border-border p-3"
              >
                <Skeleton className="size-8 rounded-lg" />
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
              <AlertTriangle className="size-4" aria-hidden="true" />
              <AlertTitle>Couldn’t load the index</AlertTitle>
              <AlertDescription>{state.message}</AlertDescription>
            </Alert>
            <div>
              <Button
                onClick={onRetry}
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

        {state.status === "ready" && nodeTypes.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Layers
              className="size-4 text-muted-foreground"
              aria-hidden="true"
            />
            {nodeTypes.map((nt) => (
              <Badge key={nt.type} variant="secondary">
                {nt.type}
                <span className="ml-1 text-muted-foreground tabular-nums">
                  {nt.count.toLocaleString()}
                </span>
              </Badge>
            ))}
          </div>
        )}

        {state.status === "ready" && sections && sections.levels.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Section levels: {sections.levels.join(" › ")}
          </p>
        )}

        {state.status === "ready" && !hasItems && (
          <Empty className="border-2 border-dashed">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BookOpen className="size-6" aria-hidden="true" />
              </EmptyMedia>
              <EmptyTitle>No index available</EmptyTitle>
              <EmptyDescription>
                This corpus doesn’t expose a section index. You can still read
                it from the start in the viewer.
              </EmptyDescription>
            </EmptyHeader>
            <Button
              onClick={() => onOpenViewer("")}
              className="gap-1.5"
              data-cuelume-press
              data-cuelume-release
            >
              <BookOpen className="size-4" aria-hidden="true" />
              Open viewer
            </Button>
          </Empty>
        )}

        {state.status === "ready" && hasItems && sections && (
          <ul className="flex flex-col gap-3" aria-label="Corpus section index">
            {sections.items.map((item) => (
              <li key={item.ref} className="rounded-lg border-2 border-border">
                <div className="flex items-center justify-between gap-2 px-3 py-2">
                  <Link
                    to={`/corpus/${encodeURIComponent(corpusId)}/view?ref=${encodeURIComponent(item.ref)}`}
                    className="min-w-0 truncate text-sm font-medium hover:underline"
                    title={item.title}
                  >
                    {item.title}
                  </Link>
                  <Badge variant="secondary" className="shrink-0">
                    {item.children.length}
                  </Badge>
                </div>
                {item.children.length > 0 && (
                  <ul className="divide-y border-t">
                    {item.children.map((child) => (
                      <li key={child.ref}>
                        <Link
                          to={`/corpus/${encodeURIComponent(corpusId)}/view?ref=${encodeURIComponent(child.ref)}`}
                          className="flex items-center justify-between gap-2 px-3 py-2 text-sm text-neutral-600 transition-colors hover:bg-muted/50 hover:text-foreground dark:text-neutral-300"
                        >
                          <span
                            className="min-w-0 truncate"
                            title={child.title}
                          >
                            {child.title}
                          </span>
                          <ChevronRight
                            className="size-4 shrink-0 text-muted-foreground"
                            aria-hidden="true"
                          />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      {state.status === "ready" && (
        <CardFooter className="justify-end">
          <Button
            variant="outline"
            onClick={() => onOpenViewer("")}
            className="gap-1.5"
            data-cuelume-press
            data-cuelume-release
          >
            <BookOpen className="size-4" aria-hidden="true" />
            Open viewer
          </Button>
        </CardFooter>
      )}
    </Card>
  )
}
