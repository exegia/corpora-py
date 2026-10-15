import { useEffect, useId, useRef } from "react"
import { useAtom, useAtomValue, useSetAtom, useStore } from "jotai"
import { KeyRound, LoaderCircle, Plus, RefreshCw, Search, Server } from "lucide-react"
import { ConversionForm } from "@/components/conversion-form"
import { ConversionJobDetail } from "@/components/conversion-job-detail"
import { ConversionJobStatus, conversionDate } from "@/components/conversion-job-status"
import { ConversionJobsEmpty } from "@/components/examples/c-icon-stack-5"
import { Badge } from "@/components/reui/badge"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { cn } from "@/lib/utils"
import type { ConversionJob, ConversionJobsController } from "@/shared/conversion"
import type { SidecarStatus } from "@/shared/rpc"
import {
    conversionClientAtom,
    conversionSessionAtom,
    jobsAnnouncementAtom,
    jobsCreatingAtom,
    jobsLocalErrorAtom,
    jobsQueryAtom,
    jobsRefreshingAtom,
    jobsSelectedIdAtom,
    jobsStatusFilterAtom,
    resetConversionFormAtom
} from "@/shared/store"

const statuses: { value: ConversionJob["status"]; label: string }[] = [
    { value: "queued", label: "Queued" },
    { value: "running", label: "Running" },
    { value: "succeeded", label: "Succeeded" },
    { value: "failed", label: "Failed" }
]

export function ConversionJobs({
    backend,
    conversions,
    onOpenJob
}: {
    backend: SidecarStatus
    conversions: ConversionJobsController
    onOpenJob?: (job: ConversionJob) => void
}) {
    const headingId = useId()
    const historyHeadingId = useId()
    const workspaceId = useId()
    const store = useStore()
    const session = useAtomValue(conversionSessionAtom)
    const client = useAtomValue(conversionClientAtom)
    const [creatingValue, setCreating] = useAtom(jobsCreatingAtom)
    const creating = creatingValue ?? conversions.jobs.length === 0
    const [selectedId, setSelectedId] = useAtom(jobsSelectedIdAtom)
    const [query, setQuery] = useAtom(jobsQueryAtom)
    const [statusFilter, setStatusFilter] = useAtom(jobsStatusFilterAtom)
    const [refreshing, setRefreshing] = useAtom(jobsRefreshingAtom)
    const [localError, setLocalError] = useAtom(jobsLocalErrorAtom)
    const [announcement, setAnnouncement] = useAtom(jobsAnnouncementAtom)
    const resetForm = useSetAtom(resetConversionFormAtom)
    const refreshingRef = useRef<symbol | null>(null)
    const currentController = useRef(conversions)
    currentController.current = conversions
    const detailRef = useRef<HTMLDivElement>(null)
    const backendReady = backend.state === "ready" && Boolean(backend.url)
    const jobs = [...conversions.jobs].sort((left, right) => right.created_at - left.created_at)
    const selected = jobs.find((job) => job.id === selectedId) ?? jobs[0] ?? null
    const activeCount = jobs.filter((job) => job.status === "queued" || job.status === "running").length
    const filtered = jobs.filter(
        (job) =>
            (statusFilter === "all" || job.status === statusFilter) &&
            `${job.display_name ?? ""} ${job.name} ${job.id}`
                .toLocaleLowerCase()
                .includes(query.trim().toLocaleLowerCase())
    )
    const requestError = localError ?? conversions.error
    const listBusy = refreshing || conversions.isLoading

    useEffect(() => {
        if (
            store.get(conversionSessionAtom) === session &&
            store.get(conversionClientAtom) === client &&
            store.get(jobsCreatingAtom) === null
        )
            setCreating(conversions.jobs.length === 0)
    }, [store, setCreating, creatingValue, conversions.jobs.length, session, client])

    useEffect(() => {
        refreshingRef.current = null
    }, [client, session, conversions.refresh])

    function isCurrentSession() {
        return store.get(conversionSessionAtom) === session && store.get(conversionClientAtom) === client
    }
    function focusDetail() {
        requestAnimationFrame(() => detailRef.current?.focus())
    }
    function startNew() {
        setCreating(true)
        setLocalError(null)
        conversions.clearError()
        focusDetail()
    }
    function selectJob(job: ConversionJob) {
        setSelectedId(job.id)
        setLocalError(null)
        if (onOpenJob) {
            onOpenJob(job)
            return
        }
        setCreating(false)
        focusDetail()
    }
    function submitted(job: ConversionJob) {
        if (!isCurrentSession() || currentController.current.submit !== conversions.submit) return
        resetForm()
        setSelectedId(job.id)
        setAnnouncement(`Conversion submitted: ${job.display_name || job.name}.`)
        setCreating(false)
        if (onOpenJob) {
            onOpenJob(job)
            return
        }
        focusDetail()
    }
    async function refresh() {
        if (!backendReady || refreshingRef.current || store.get(jobsRefreshingAtom) || conversions.isLoading) return
        const request = Symbol()
        refreshingRef.current = request
        setRefreshing(true)
        setLocalError(null)
        conversions.clearError()
        try {
            await conversions.refresh()
        } catch (cause) {
            if (isCurrentSession() && currentController.current.refresh === conversions.refresh) {
                setLocalError(cause instanceof Error ? cause.message : "Could not refresh conversion jobs.")
            }
        } finally {
            if (refreshingRef.current === request) refreshingRef.current = null
            if (isCurrentSession() && currentController.current.refresh === conversions.refresh) setRefreshing(false)
        }
    }

    return (
        <section
            aria-labelledby={headingId}
            className="flex min-w-0 flex-col gap-5">
            <header className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-3">
                        <h1
                            id={headingId}
                            className="text-2xl font-semibold tracking-tight">
                            Conversion jobs
                        </h1>
                        {activeCount > 0 && (
                            <Badge
                                variant="primary-light"
                                radius="full">
                                {activeCount} active
                            </Badge>
                        )}
                    </div>
                    <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
                        Turn documents into corpora. Inspect each stage, read the logs, and keep the finished output.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        type="button"
                        variant="outline"
                        disabled={!backendReady || listBusy}
                        onClick={() => void refresh()}
                        aria-busy={listBusy}>
                        <RefreshCw
                            aria-hidden="true"
                            className={listBusy ? "motion-safe:animate-spin" : undefined}
                        />
                        {listBusy ? "Refreshing…" : "Refresh"}
                    </Button>
                    <Button
                        type="button"
                        disabled={conversions.isSubmitting}
                        onClick={startNew}>
                        <Plus aria-hidden="true" />
                        New conversion
                    </Button>
                </div>
            </header>
            {!backendReady && (
                <Alert
                    variant={backend.state === "failed" ? "destructive" : "warning"}
                    role="status">
                    <Server
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                    <AlertTitle>
                        {backend.state === "starting" ? "Sidecar is starting" : "Sidecar is not ready"}
                    </AlertTitle>
                    <AlertDescription className="text-xs leading-relaxed">
                        {backend.error ||
                            "You can prepare a conversion, but submission, refresh, and downloads need a ready sidecar."}{" "}
                        Existing jobs and logs remain visible.
                    </AlertDescription>
                </Alert>
            )}
            {backend.authRequired === true && (
                <Alert>
                    <KeyRound
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                    <AlertTitle>Authentication required</AlertTitle>
                    <AlertDescription className="text-xs leading-relaxed">
                        Configure a request token in app Settings. Conversion requests use that token; authentication is
                        not bypassed.
                    </AlertDescription>
                </Alert>
            )}
            {requestError && (
                <Alert
                    variant="destructive"
                    role="alert">
                    <AlertTitle>Conversion request failed</AlertTitle>
                    <AlertDescription className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                        {requestError}
                    </AlertDescription>
                    <AlertAction>
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                                setLocalError(null)
                                conversions.clearError()
                            }}>
                            Dismiss
                        </Button>
                    </AlertAction>
                </Alert>
            )}
            <p
                role="status"
                className="sr-only">
                {announcement}
            </p>
            <div className="grid min-w-0 items-start gap-5 @3xl:grid-cols-[18rem_minmax(0,1fr)]">
                <aside
                    aria-labelledby={historyHeadingId}
                    className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-xs">
                    <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
                        <h2
                            id={historyHeadingId}
                            className="text-sm font-semibold">
                            Jobs
                        </h2>
                        <span className="text-xs tabular-nums text-muted-foreground">{jobs.length} jobs</span>
                    </header>
                    {jobs.length > 0 && (
                        <div className="flex flex-col gap-2 border-b border-border p-3">
                            <Field>
                                <FieldLabel className="sr-only">Search conversion jobs</FieldLabel>
                                <Input
                                    type="search"
                                    value={query}
                                    onChange={(event) => setQuery(event.target.value)}
                                    placeholder="Search jobs…"
                                />
                            </Field>
                            <Field>
                                <FieldLabel className="sr-only">Filter jobs by status</FieldLabel>
                                <NativeSelect
                                    value={statusFilter}
                                    onChange={(event) =>
                                        setStatusFilter(
                                            statuses.find((status) => status.value === event.target.value)?.value ??
                                                "all"
                                        )
                                    }>
                                    <NativeSelectOption value="all">All statuses</NativeSelectOption>
                                    {statuses.map((status) => (
                                        <NativeSelectOption
                                            key={status.value}
                                            value={status.value}>
                                            {status.label}
                                        </NativeSelectOption>
                                    ))}
                                </NativeSelect>
                            </Field>
                        </div>
                    )}
                    {jobs.length === 0 ? (
                        conversions.isLoading ? (
                            <p
                                role="status"
                                className="flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
                                <LoaderCircle
                                    className="size-4 motion-safe:animate-spin"
                                    aria-hidden="true"
                                />
                                Loading jobs…
                            </p>
                        ) : (
                            <ConversionJobsEmpty
                                onCreate={startNew}
                                compact
                            />
                        )
                    ) : filtered.length ? (
                        <ul
                            aria-label="Conversion jobs"
                            className="flex max-h-64 flex-col gap-1 overflow-y-auto p-2 @3xl:max-h-[36rem]">
                            {filtered.map((job) => (
                                <li key={job.id}>
                                    <button
                                        type="button"
                                        onClick={() => selectJob(job)}
                                        aria-pressed={!creating && selected?.id === job.id}
                                        aria-controls={workspaceId}
                                        className={cn(
                                            "flex w-full flex-col gap-2 rounded-lg border px-3 py-3 text-start outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                            !creating && selected?.id === job.id
                                                ? "border-primary/30 bg-accent"
                                                : "border-transparent hover:bg-muted/50"
                                        )}>
                                        <span className="flex items-start justify-between gap-2">
                                            <span
                                                className="min-w-0 truncate text-sm font-medium"
                                                title={job.display_name || job.name}>
                                                {job.display_name || job.name}
                                            </span>
                                            <ConversionJobStatus status={job.status} />
                                        </span>
                                        <span className="text-xs tabular-nums text-muted-foreground">
                                            {conversionDate(job.created_at)}
                                        </span>
                                        <span className="truncate text-xs text-muted-foreground">
                                            {job.last_log || `Output: .${job.output_format}`}
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <div className="flex flex-col items-center gap-3 px-4 py-8 text-center">
                            <Search
                                className="size-5 text-muted-foreground"
                                aria-hidden="true"
                                strokeWidth={1.5}
                            />
                            <p className="text-sm text-muted-foreground">No jobs match these filters.</p>
                            <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => {
                                    setQuery("")
                                    setStatusFilter("all")
                                }}>
                                Clear filters
                            </Button>
                        </div>
                    )}
                </aside>
                <div
                    id={workspaceId}
                    ref={detailRef}
                    tabIndex={-1}
                    className="min-w-0 rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {creating ? (
                        <ConversionForm
                            conversions={conversions}
                            backendReady={backendReady}
                            onSubmitted={submitted}
                            onClose={() => {
                                setCreating(false)
                                focusDetail()
                            }}
                        />
                    ) : selected ? (
                        <ConversionJobDetail
                            key={selected.id}
                            job={selected}
                            conversions={conversions}
                            backendReady={backendReady}
                        />
                    ) : (
                        <ConversionJobsEmpty onCreate={startNew} />
                    )}
                </div>
            </div>
        </section>
    )
}
