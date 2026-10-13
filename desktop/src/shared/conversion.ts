export type SourceFormat = "epub" | "html" | "xml" | "tei" | "pdf" | "plain" | "tf_zip" | "tei_zip"
export type OutputFormat = "corpus" | "cusx" | "ctei"
export type CorpusCategory = "document" | "book" | "religious"

export interface ConversionOptions {
    name: string
    description: string
    source_format: SourceFormat
    output_format: OutputFormat
    category?: CorpusCategory
}

export interface ConversionEvent {
    sequence: number
    timestamp: number
    level: "debug" | "info" | "warning" | "error"
    message: string
    stage: string | null
}

export interface ConversionStep {
    id: string
    title: string
    status: "pending" | "running" | "completed" | "failed" | "skipped"
}

export interface ConversionJob {
    id: string
    name: string
    display_name: string | null
    source_format: string
    output_format: string
    status: "queued" | "running" | "succeeded" | "failed"
    created_at: number
    started_at: number | null
    finished_at: number | null
    error: string | null
    logs: string[]
    last_log: string | null
    events: ConversionEvent[]
    steps: ConversionStep[]
    validation: Record<string, unknown> | null
    result_filename: string
    download_ready: boolean
}

export interface ConversionJobsController {
    jobs: ConversionJob[]
    isLoading: boolean
    isSubmitting: boolean
    error: string | null
    refresh: () => Promise<void>
    submit: (file: File, options: ConversionOptions) => Promise<ConversionJob | null>
    download: (job: ConversionJob) => Promise<void>
    clearError: () => void
}
