import type { ConversionEvent, ConversionJob, ConversionOptions, ConversionStep, OutputFormat, SourceFormat } from "@/shared/conversion"

// Keep in sync with admin.services.api._MAX_UPLOAD_BYTES.
export const MAX_UPLOAD_BYTES = 500 * 1024 * 1024
export const SOURCE_FORMATS: { value: SourceFormat; label: string; accept: string }[] = [
    { value: "epub", label: "EPUB", accept: ".epub" },
    { value: "html", label: "HTML", accept: ".html,.htm" },
    { value: "xml", label: "XML", accept: ".xml" },
    { value: "tei", label: "TEI XML", accept: ".tei,.xml" },
    { value: "pdf", label: "PDF", accept: ".pdf" },
    { value: "plain", label: "Plain text", accept: ".txt,.text,.md" },
    { value: "tf_zip", label: "Text-Fabric ZIP", accept: ".zip" },
    { value: "tei_zip", label: "TEI ZIP", accept: ".zip" }
]
export const OUTPUT_FORMATS: { value: OutputFormat; label: string; description: string }[] = [
    { value: "corpus", label: ".corpus", description: "Text-Fabric dataset and compiled cache." },
    { value: "cusx", label: ".cusx", description: "Canonical corpus exchange archive." },
    { value: "ctei", label: ".ctei", description: "TEI document exchange archive." }
]

export function inferSourceFormat(filename: string): SourceFormat | null {
    const name = filename.toLowerCase()
    // Generic ZIP contents require an explicit choice, even with a suggestive name.
    if (name.endsWith(".zip")) return null
    return SOURCE_FORMATS.find(format => format.accept.split(",").some(extension => name.endsWith(extension)))?.value ?? null
}

export function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes < 0) return "—"
    if (bytes === 0) return "0 B"
    const units = ["B", "KiB", "MiB", "GiB"]
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
    return `${Number((bytes / 1024 ** index).toFixed(1))} ${units[index]}`
}

export function isTerminalJob(job: ConversionJob): boolean {
    return job.status === "succeeded" || job.status === "failed"
}

export function buildConversionForm(file: File, options: ConversionOptions): FormData {
    if (!file.size || file.size > MAX_UPLOAD_BYTES) throw new Error("Choose a nonempty source file up to 500 MiB.")
    if (!options.name.trim()) throw new Error("Enter a corpus name.")
    if ((options.source_format === "tf_zip" || options.source_format === "tei_zip") && options.output_format !== "corpus") {
        throw new Error("Source dataset ZIPs can only produce a .corpus archive.")
    }
    const body = new FormData()
    body.set("file", file, file.name)
    body.set("name", options.name.trim())
    body.set("description", options.description.trim())
    body.set("source_format", options.source_format)
    body.set("output_format", options.output_format)
    if (options.category) body.set("category", options.category)
    return body
}

export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value)
}
const nullableString = (value: unknown): string | null => typeof value === "string" ? value : null
const nullableNumber = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null

function parseEvent(value: unknown): ConversionEvent | null {
    if (!isRecord(value)) return null
    const { sequence, timestamp, level, message, stage } = value
    if (typeof sequence !== "number" || !Number.isInteger(sequence) || sequence < 1 ||
        typeof timestamp !== "number" || !Number.isFinite(timestamp) || typeof message !== "string" ||
        (level !== "debug" && level !== "info" && level !== "warning" && level !== "error")) return null
    return { sequence, timestamp, level, message, stage: nullableString(stage) }
}
function parseStep(value: unknown): ConversionStep | null {
    if (!isRecord(value)) return null
    const { id, title, status } = value
    if (typeof id !== "string" || typeof title !== "string" ||
        (status !== "pending" && status !== "running" && status !== "completed" && status !== "failed" && status !== "skipped")) return null
    return { id, title, status }
}

export function parseConversionJob(value: unknown): ConversionJob {
    if (!isRecord(value)) throw new Error("The backend returned an invalid conversion job.")
    const { id, name, source_format, output_format, status, created_at } = value
    if (typeof id !== "string" || !id || typeof name !== "string" ||
        typeof source_format !== "string" || typeof output_format !== "string" ||
        typeof created_at !== "number" || !Number.isFinite(created_at) ||
        (status !== "queued" && status !== "running" && status !== "succeeded" && status !== "failed")) {
        throw new Error("The backend returned an invalid conversion job.")
    }
    return {
        id, name, source_format, output_format, status, created_at,
        display_name: nullableString(value.display_name), started_at: nullableNumber(value.started_at),
        finished_at: nullableNumber(value.finished_at), error: nullableString(value.error),
        logs: Array.isArray(value.logs) ? value.logs.filter((log): log is string => typeof log === "string") : [],
        last_log: nullableString(value.last_log),
        events: Array.isArray(value.events) ? value.events.flatMap(event => { const parsed = parseEvent(event); return parsed ? [parsed] : [] }) : [],
        steps: Array.isArray(value.steps) ? value.steps.flatMap(step => { const parsed = parseStep(step); return parsed ? [parsed] : [] }) : [],
        validation: isRecord(value.validation) ? value.validation : null,
        result_filename: typeof value.result_filename === "string" ? value.result_filename : `${name}.${output_format}`,
        download_ready: value.download_ready === true
    }
}

export function parseConversionList(value: unknown): ConversionJob[] {
    if (!isRecord(value) || !Array.isArray(value.jobs)) throw new Error("The backend returned an invalid job list.")
    // /ingest shares the job registry, but is a distinct pipeline and option set.
    return value.jobs.filter(job => isRecord(job) && SOURCE_FORMATS.some(format => format.value === job.source_format))
        .map(parseConversionJob)
}

function detailMessages(value: unknown): string[] {
    if (typeof value === "string") return [value]
    if (Array.isArray(value)) return value.flatMap(detailMessages)
    if (!isRecord(value)) return []
    const messages = ["message", "msg", "error", "reason", "reasons", "errors", "warnings"].flatMap(key => detailMessages(value[key]))
    return messages.length ? messages : [JSON.stringify(value)]
}

export class ConversionRequestError extends Error {
    constructor(readonly status: number, message: string) { super(message); this.name = "ConversionRequestError" }
}

export async function requireSuccessfulResponse(response: Response): Promise<Response> {
    if (response.ok) return response
    let detail: unknown
    try { detail = await response.json() } catch { detail = null }
    const prefix = response.status === 401 ? "Authentication failed. Set a valid Supabase request token in Settings." :
        response.status === 413 ? "The source exceeds the backend upload limit (500 MiB)." :
        response.status === 429 ? "The conversion queue is full. Wait for an active job to finish." :
        `Conversion request failed (HTTP ${response.status}).`
    const messages = detailMessages(isRecord(detail) ? detail.detail ?? detail : detail)
    throw new ConversionRequestError(response.status, [prefix, ...new Set(messages)].join("\n"))
}

export function safeDownloadFilename(disposition: string | null, fallback: string): string {
    const encoded = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
    const plain = disposition?.match(/filename="([^"]+)"|filename=([^;]+)/i)
    let filename = plain?.[1] ?? plain?.[2] ?? fallback
    if (encoded) { try { filename = decodeURIComponent(encoded) } catch { /* Use the plain filename for malformed headers. */ } }
    return filename.replace(/[\\/\u0000-\u001f\u007f]/g, "_").trim().replace(/^\.+/, "") || "conversion.corpus"
}
