import {
    buildConversionForm,
    ConversionRequestError,
    isRecord,
    isTerminalJob,
    parseConversionJob,
    parseConversionList,
    requireSuccessfulResponse,
    safeDownloadFilename
} from "@/lib/conversion"
import type { ConversionJob, ConversionOptions } from "@/shared/conversion"

export interface ConversionSnapshot {
    jobs: ConversionJob[]
    isLoading: boolean
    isSubmitting: boolean
    error: string | null
}
export interface ConversionRuntime {
    fetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    now: () => number
    schedule: (callback: () => void, delay: number) => () => void
    save: (blob: Blob, filename: string) => void
}
const browserRuntime: ConversionRuntime = {
    fetch: (...args) => fetch(...args),
    now: () => Date.now(),
    schedule: (callback, delay) => {
        const timer = setTimeout(callback, delay)
        return () => clearTimeout(timer)
    },
    save: (blob, filename) => {
        const url = URL.createObjectURL(blob)
        const link = document.createElement("a")
        link.href = url
        link.download = filename
        document.body.append(link)
        link.click()
        link.remove()
        // WKWebView needs time to hand the blob to its download handler.
        setTimeout(() => URL.revokeObjectURL(url), 60_000)
    }
}
const POLL_MS = 1500
const messageOf = (error: unknown): string =>
    error instanceof Error ? error.message : "Could not reach the conversion backend."

/** Background ownership belongs to the app, never to a lazily mounted tab. */
export class ConversionClient {
    private snapshot: ConversionSnapshot = { jobs: [], isLoading: false, isSubmitting: false, error: null }
    private listeners = new Set<() => void>()
    private enabled = false
    private generation = 0
    private requests = new AbortController()
    private cancelTimer: (() => void) | null = null
    private pendingRefresh: Promise<void> | null = null
    private pendingSubmit: Promise<ConversionJob | null> | null = null
    private retryList = false
    private authBlocked = false

    constructor(
        private readonly endpoint: string | null,
        private readonly token: string,
        private readonly runtime: ConversionRuntime = browserRuntime
    ) {}
    getSnapshot = (): ConversionSnapshot => this.snapshot
    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => this.listeners.delete(listener)
    }
    private publish(update: Partial<ConversionSnapshot>): void {
        const next = { ...this.snapshot, ...update }
        if (JSON.stringify(next) === JSON.stringify(this.snapshot)) return
        this.snapshot = next
        for (const listener of this.listeners) listener()
    }
    clearError = (): void => this.publish({ error: null })
    private clearTimer(): void {
        this.cancelTimer?.()
        this.cancelTimer = null
    }
    start = (): void => {
        if (this.enabled || !this.endpoint) return
        this.enabled = true
        this.requests = new AbortController()
        this.authBlocked = false
        void this.refresh()
    }
    stop = (): void => {
        this.enabled = false
        this.generation++
        this.clearTimer()
        this.requests.abort()
        this.pendingRefresh = null
        this.pendingSubmit = null
        this.publish({ isLoading: false, isSubmitting: false })
    }
    private isCurrent(generation: number): boolean {
        return this.enabled && generation === this.generation
    }
    private schedule(): void {
        this.clearTimer()
        if (
            !this.enabled ||
            this.authBlocked ||
            (!this.retryList && !this.snapshot.jobs.some((job) => !isTerminalJob(job)))
        )
            return
        this.cancelTimer = this.runtime.schedule(() => {
            this.cancelTimer = null
            void this.readJobs(this.retryList)
        }, POLL_MS)
    }
    private reportError(error: unknown): void {
        if (error instanceof ConversionRequestError && (error.status === 401 || error.status === 403)) {
            this.authBlocked = true
            this.clearTimer()
        }
        this.publish({ error: messageOf(error) })
    }
    private async request<T>(path: string, init: RequestInit, decode: (response: Response) => Promise<T>): Promise<T> {
        if (!this.enabled || !this.endpoint)
            throw new Error("The sidecar is not ready. Check the backend connection first.")
        const controller = new AbortController()
        const onAbort = () => controller.abort()
        const parentSignal = this.requests.signal
        parentSignal.addEventListener("abort", onAbort, { once: true })
        const cancelDeadline = this.runtime.schedule(
            () => controller.abort(),
            init.method === "POST" ? 120_000 : 30_000
        )
        const headers = new Headers(init.headers)
        if (this.token) headers.set("Authorization", `Bearer ${this.token}`)
        try {
            const response = await this.runtime.fetch(`${this.endpoint.replace(/\/$/, "")}${path}`, {
                ...init,
                headers,
                signal: controller.signal
            })
            return await decode(await requireSuccessfulResponse(response))
        } catch (error) {
            if (controller.signal.aborted && !parentSignal.aborted) {
                throw new Error(
                    init.method === "POST"
                        ? "Upload timed out. The server may have accepted it; refresh the job list before submitting again."
                        : "The backend request timed out. Tracking will retry while jobs are active."
                )
            }
            throw error
        } finally {
            cancelDeadline()
            parentSignal.removeEventListener("abort", onAbort)
        }
    }
    private merge(jobs: ConversionJob[]): void {
        const previous = new Map(this.snapshot.jobs.map((job) => [job.id, job]))
        for (const job of jobs) previous.set(job.id, job)
        this.publish({ jobs: [...previous.values()].sort((a, b) => b.created_at - a.created_at) })
    }
    refresh = (): Promise<void> => {
        this.authBlocked = false
        return this.readJobs(true)
    }
    private readJobs(full: boolean): Promise<void> {
        if (!this.enabled) return Promise.resolve()
        if (this.pendingRefresh) return this.pendingRefresh
        this.clearTimer()
        const generation = this.generation
        if (!this.snapshot.jobs.length) this.publish({ isLoading: true })
        const request = Promise.resolve().then(async () => {
            if (!this.isCurrent(generation)) return
            try {
                let jobs: ConversionJob[]
                if (full) {
                    // Read every page so old running jobs cannot disappear behind newer jobs.
                    jobs = []
                    let offset = 0
                    let total = 0
                    do {
                        const payload: unknown = await this.request(
                            `/convert?offset=${offset}&limit=200`,
                            {},
                            (response) => response.json()
                        )
                        jobs.push(...parseConversionList(payload))
                        if (!isRecord(payload) || !Array.isArray(payload.jobs)) throw new Error("Invalid job list.")
                        if (typeof payload.total !== "number" || !Number.isInteger(payload.total) || payload.total < 0)
                            throw new Error("Invalid job count.")
                        total = payload.total
                        if (!payload.jobs.length) break
                        offset += payload.jobs.length
                    } while (offset < total && this.isCurrent(generation))
                    // Keep locally accepted jobs missing from a racing list snapshot until individually checked.
                    if (this.isCurrent(generation)) {
                        this.retryList = false
                        const seen = new Set(jobs.map((job) => job.id))
                        jobs.push(...this.snapshot.jobs.filter((job) => !seen.has(job.id) && !isTerminalJob(job)))
                        const uniqueJobs = new Map(jobs.map((job) => [job.id, job]))
                        this.publish({
                            jobs: [...uniqueJobs.values()].sort((a, b) => b.created_at - a.created_at),
                            error: null
                        })
                    }
                } else {
                    const active = this.snapshot.jobs.filter((job) => !isTerminalJob(job))
                    const results = await Promise.allSettled(
                        active.map(async (job) => {
                            const payload: unknown = await this.request(
                                `/convert/${encodeURIComponent(job.id)}`,
                                {},
                                (response) => response.json()
                            )
                            const incoming = parseConversionJob(payload)
                            if (incoming.id !== job.id) throw new Error("The backend returned a different job id.")
                            return incoming
                        })
                    )
                    if (!this.isCurrent(generation)) return
                    jobs = []
                    let error: unknown = null
                    results.forEach((result, index) => {
                        if (result.status === "fulfilled") jobs.push(result.value)
                        else if (result.reason instanceof ConversionRequestError && result.reason.status === 404) {
                            this.publish({ jobs: this.snapshot.jobs.filter((job) => job.id !== active[index].id) })
                            error = new Error(
                                "A tracked conversion is no longer available. Its retention period may have expired."
                            )
                        } else {
                            if (
                                result.reason instanceof ConversionRequestError &&
                                (result.reason.status === 401 || result.reason.status === 403)
                            ) {
                                this.authBlocked = true
                                error = result.reason
                            } else if (!(
                                error instanceof ConversionRequestError &&
                                (error.status === 401 || error.status === 403)
                            )) {
                                error = result.reason
                            }
                        }
                    })
                    this.merge(jobs)
                    if (error) this.reportError(error)
                    else this.clearError()
                }
            } catch (error) {
                if (!this.isCurrent(generation)) return
                if (full) this.retryList = true
                this.reportError(error)
            } finally {
                if (this.isCurrent(generation)) {
                    this.pendingRefresh = null
                    this.publish({ isLoading: false })
                    this.schedule()
                }
            }
        })
        this.pendingRefresh = request
        return request
    }
    submit = (file: File, options: ConversionOptions): Promise<ConversionJob | null> => {
        if (this.pendingSubmit) return this.pendingSubmit
        const generation = this.generation
        this.publish({ isSubmitting: true, error: null })
        const request = Promise.resolve().then(async () => {
            if (!this.isCurrent(generation)) return null
            try {
                const payload: unknown = await this.request(
                    "/convert",
                    { method: "POST", body: buildConversionForm(file, options) },
                    (response) => response.json()
                )
                if (!isRecord(payload) || typeof payload.job_id !== "string" || !payload.job_id) {
                    throw new Error("The upload response was incomplete. Refresh the job list before submitting again.")
                }
                if (!this.isCurrent(generation)) return null
                // Acceptance is success even if the first status read fails. Never re-POST to retry tracking.
                const job: ConversionJob = {
                    id: payload.job_id,
                    name: options.name.trim(),
                    display_name: null,
                    source_format: options.source_format,
                    output_format: options.output_format,
                    status: "queued",
                    created_at: this.runtime.now() / 1000,
                    started_at: null,
                    finished_at: null,
                    error: null,
                    logs: [],
                    last_log: null,
                    events: [],
                    steps: [],
                    validation: null,
                    result_filename: `${options.name.trim()}.${options.output_format}`,
                    download_ready: false
                }
                this.merge([job])
                this.authBlocked = false
                this.schedule()
                return job
            } catch (error) {
                if (this.isCurrent(generation)) this.reportError(error)
                return null
            } finally {
                if (this.isCurrent(generation)) {
                    this.pendingSubmit = null
                    this.publish({ isSubmitting: false })
                }
            }
        })
        this.pendingSubmit = request
        return request
    }
    download = async (job: ConversionJob): Promise<void> => {
        const generation = this.generation
        try {
            if (job.status !== "succeeded" || !job.download_ready)
                throw new Error("The conversion result is not ready to download.")
            const result = await this.request(
                `/convert/${encodeURIComponent(job.id)}/download`,
                {},
                async (response) => ({
                    blob: await response.blob(),
                    filename: safeDownloadFilename(response.headers.get("Content-Disposition"), job.result_filename)
                })
            )
            if (this.isCurrent(generation)) this.runtime.save(result.blob, result.filename)
        } catch (error) {
            if (this.isCurrent(generation)) {
                this.reportError(error)
                throw error
            }
        }
    }
}
