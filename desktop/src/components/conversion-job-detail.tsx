import { useId, useRef } from "react"
import { useAtom, useAtomValue, useStore } from "jotai"
import { Download, FileArchive, LoaderCircle } from "lucide-react"
import { ConversionProgressSteps } from "@/components/examples/c-stepper-21"
import { ConversionJobStatus, conversionDate } from "@/components/conversion-job-status"
import { ConversionLogs } from "@/components/conversion-logs"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { OUTPUT_FORMATS, SOURCE_FORMATS, isTerminalJob } from "@/lib/conversion"
import type { ConversionJob, ConversionJobsController } from "@/shared/conversion"
import { conversionClientAtom, conversionDetailAtomsFor, conversionSessionAtom } from "@/shared/store"

export function ConversionJobDetail({
    job,
    conversions,
    backendReady
}: {
    job: ConversionJob
    conversions: ConversionJobsController
    backendReady: boolean
}) {
    const headingId = useId()
    const store = useStore()
    const session = useAtomValue(conversionSessionAtom)
    const client = useAtomValue(conversionClientAtom)
    const key = `${session}:${job.id}`
    const atoms = conversionDetailAtomsFor(key)
    const [stage, setStage] = useAtom(atoms.stage)
    const [downloading, setDownloading] = useAtom(atoms.downloading)
    const [downloadError, setDownloadError] = useAtom(atoms.downloadError)
    const downloadLock = useRef<string | null>(null)
    const currentController = useRef(conversions)
    currentController.current = conversions
    const available = job.status === "succeeded" && job.download_ready
    const active = !isTerminalJob(job)
    const title = job.display_name || job.name

    async function download() {
        if (!available || !backendReady || downloadLock.current === key || store.get(atoms.downloading)) return
        downloadLock.current = key
        setDownloading(true)
        setDownloadError(null)
        conversions.clearError()
        try {
            await conversions.download(job)
        } catch (cause) {
            if (
                store.get(conversionSessionAtom) === session &&
                store.get(conversionClientAtom) === client &&
                currentController.current.download === conversions.download
            ) {
                setDownloadError(
                    cause instanceof Error
                        ? cause.message
                        : "Could not download this result. Try again when the sidecar is ready."
                )
            }
        } finally {
            if (downloadLock.current === key) downloadLock.current = null
            // The captured setter clears this job's flag, not the newly selected job's.
            if (store.get(conversionSessionAtom) === session) setDownloading(false)
        }
    }

    return (
        <article
            aria-labelledby={headingId}
            className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-xs">
            <header className="flex flex-col gap-3 border-b border-border px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <h2
                            id={headingId}
                            className="break-words text-lg font-semibold tracking-tight">
                            {title}
                        </h2>
                        <p className="break-all text-xs text-muted-foreground">{job.id}</p>
                    </div>
                    <ConversionJobStatus status={job.status} />
                </div>
                <p className="text-xs text-muted-foreground">
                    {SOURCE_FORMATS.find((format) => format.value === job.source_format)?.label ?? job.source_format} →{" "}
                    {OUTPUT_FORMATS.find((format) => format.value === job.output_format)?.label ?? job.output_format}
                    <span
                        aria-hidden="true"
                        className="mx-2">
                        ·
                    </span>
                    Submitted {conversionDate(job.created_at)}
                </p>
            </header>
            <div className="flex flex-col gap-5 p-5">
                <p
                    role="status"
                    className="text-sm text-muted-foreground">
                    {job.status === "queued"
                        ? "Waiting for a conversion worker."
                        : job.status === "running"
                          ? "Conversion is running. You can leave this tab while the job continues."
                          : job.status === "succeeded"
                            ? "Conversion succeeded."
                            : "Conversion failed. Check the error and logs for details."}
                </p>
                {job.error && (
                    <Alert
                        variant="destructive"
                        role="alert">
                        <AlertTitle>Conversion error</AlertTitle>
                        <AlertDescription className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                            {job.error}
                        </AlertDescription>
                    </Alert>
                )}
                <ConversionProgressSteps
                    steps={job.steps}
                    selectedStage={stage}
                    onSelectStage={setStage}
                />
                <Separator />
                <ConversionLogs
                    job={job}
                    stage={stage}
                    onClearStage={() => setStage(null)}
                />
                {job.validation && (
                    <details className="rounded-lg border border-border px-3 py-2">
                        <summary className="cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
                            Backend validation report
                        </summary>
                        <pre className="mt-3 max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs text-muted-foreground">
                            {JSON.stringify(job.validation, null, 2)}
                        </pre>
                    </details>
                )}
                <Separator />
                <section
                    aria-label="Conversion result"
                    className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex min-w-0 flex-1 items-center gap-3">
                            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
                                <FileArchive
                                    className="size-5"
                                    aria-hidden="true"
                                    strokeWidth={1.5}
                                />
                            </span>
                            <div className="flex min-w-0 flex-col gap-1">
                                <h3 className="text-sm font-semibold">
                                    {available ? "Result ready" : "Conversion result"}
                                </h3>
                                <p className="break-all text-xs text-muted-foreground">
                                    {available
                                        ? job.result_filename
                                        : active
                                          ? "Available after the conversion succeeds."
                                          : job.status === "failed"
                                            ? "No result is available for this failed job."
                                            : "The backend has not marked the result as downloadable."}
                                </p>
                            </div>
                        </div>
                        <Button
                            type="button"
                            variant={available ? "default" : "outline"}
                            disabled={!available || !backendReady || downloading}
                            onClick={() => void download()}
                            aria-busy={downloading}>
                            {downloading ? (
                                <LoaderCircle
                                    className="motion-safe:animate-spin"
                                    aria-hidden="true"
                                />
                            ) : (
                                <Download aria-hidden="true" />
                            )}
                            {downloading ? "Downloading…" : "Download result"}
                        </Button>
                    </div>
                    {downloadError && (
                        <p
                            role="alert"
                            className="text-sm text-destructive-foreground">
                            {downloadError}
                        </p>
                    )}
                    <dl className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
                        <div className="flex gap-2">
                            <dt>Started</dt>
                            <dd>{job.started_at === null ? "Not started" : conversionDate(job.started_at)}</dd>
                        </div>
                        <div className="flex gap-2">
                            <dt>Finished</dt>
                            <dd>{job.finished_at === null ? "Not finished" : conversionDate(job.finished_at)}</dd>
                        </div>
                    </dl>
                </section>
            </div>
        </article>
    )
}
