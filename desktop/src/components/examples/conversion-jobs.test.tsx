import { describe, expect, test } from "bun:test"
import { renderToStaticMarkup } from "react-dom/server"
import { ConversionJobs } from "@/components/conversion-jobs"
import { ConversionJobDetail } from "@/components/conversion-job-detail"
import { validateConversionDraft, type ConversionDraft } from "@/components/conversion-form"
import { conversionLogLines, conversionLogsText, filterConversionLogs } from "@/components/conversion-logs"
import { ConversionProgressSteps } from "./c-stepper-21"
import { MAX_UPLOAD_BYTES } from "@/lib/conversion"
import type { ConversionJob, ConversionJobsController } from "@/shared/conversion"
import type { SidecarStatus } from "@/shared/rpc"

const backend: SidecarStatus = { state: "ready", url: "http://127.0.0.1:8000", error: null, authRequired: false }
function makeJob(overrides: Partial<ConversionJob> = {}): ConversionJob {
    return {
        id: "job-test",
        name: "A source",
        display_name: null,
        source_format: "epub",
        output_format: "corpus",
        status: "queued",
        created_at: 1_780_000_000,
        started_at: null,
        finished_at: null,
        error: null,
        logs: [],
        last_log: null,
        events: [],
        steps: [],
        validation: null,
        result_filename: "source.corpus",
        download_ready: false,
        ...overrides
    }
}
function controller(
    jobs: ConversionJob[] = [],
    overrides: Partial<ConversionJobsController> = {}
): ConversionJobsController {
    return {
        jobs,
        isLoading: false,
        isSubmitting: false,
        error: null,
        refresh: async () => {},
        submit: async () => null,
        download: async () => {},
        clearError: () => {},
        ...overrides
    }
}
const draft: ConversionDraft = {
    name: "A corpus",
    description: "",
    source_format: "epub",
    output_format: "corpus",
    category: ""
}

describe("conversion review validation", () => {
    test("requires source, format and nonblank name", () => {
        const file = new File(["contents"], "book.epub")
        expect(validateConversionDraft(null, draft)).toContain("Choose a source")
        expect(validateConversionDraft(file, { ...draft, name: "   " })).toContain("corpus name")
        expect(validateConversionDraft(file, { ...draft, source_format: "" })).toContain("Choose the source format")
        expect(validateConversionDraft(file, draft)).toBeNull()
    })
    test("ZIP never proceeds without an explicit choice, and dataset output is corpus only", () => {
        const file = new File(["zip contents"], "source.zip")
        expect(validateConversionDraft(file, { ...draft, source_format: "" })).toContain("explicit dataset type")
        expect(validateConversionDraft(file, { ...draft, source_format: "tf_zip", output_format: "cusx" })).toContain(
            "only produce"
        )
        expect(validateConversionDraft(file, { ...draft, source_format: "tei_zip", output_format: "ctei" })).toContain(
            "only produce"
        )
        expect(validateConversionDraft(file, { ...draft, source_format: "tf_zip" })).toBeNull()
        expect(validateConversionDraft(file, { ...draft, source_format: "tei_zip" })).toBeNull()
    })
    test("rejects a file/source mismatch and an unsupported file", () => {
        expect(validateConversionDraft(new File(["x"], "book.epub"), { ...draft, source_format: "pdf" })).toContain(
            "does not match"
        )
        expect(validateConversionDraft(new File(["x"], "script.exe"), draft)).toContain("not a supported")
        expect(MAX_UPLOAD_BYTES).toBe(500 * 1024 * 1024)
    })
})

describe("backend job telemetry", () => {
    test("filters real structured events by level, stage and case-insensitive text", () => {
        const lines = conversionLogLines(
            makeJob({
                events: [
                    {
                        sequence: 1,
                        timestamp: 1_780_000_001,
                        level: "info",
                        message: "Parsing a chapter",
                        stage: "parse"
                    },
                    {
                        sequence: 2,
                        timestamp: 1_780_000_002,
                        level: "warning",
                        message: "Missing metadata",
                        stage: "parse"
                    },
                    {
                        sequence: 3,
                        timestamp: 1_780_000_003,
                        level: "error",
                        message: "Archive write failed",
                        stage: "package"
                    }
                ]
            })
        )
        expect(filterConversionLogs(lines, ["warning"], "METADATA", "parse").map((line) => line.message)).toEqual([
            "Missing metadata"
        ])
        expect(filterConversionLogs(lines, ["info", "warning", "error"], "", "package").length).toBe(1)
        expect(filterConversionLogs(lines, [], "", null)).toEqual([])
        const text = conversionLogsText(lines)
        expect(text).toContain("[warning] [parse] Missing metadata")
        expect(text).toContain(new Date(1_780_000_002 * 1000).toISOString())
    })
    test("does not invent level, stage or time metadata for legacy log strings", () => {
        const lines = conversionLogLines(makeJob({ logs: ["ERROR is just text in a legacy message"] }))
        expect(lines[0].level).toBe("unclassified")
        expect(lines[0].stage).toBeNull()
        expect(lines[0].timestamp).toBeNull()
        expect(filterConversionLogs(lines, ["error"], "", null)).toEqual([])
        expect(conversionLogsText(lines)).toBe("[unclassified] ERROR is just text in a legacy message")
    })
    test("prefers events over duplicate legacy logs", () => {
        expect(
            conversionLogLines(
                makeJob({
                    logs: ["Duplicated"],
                    events: [
                        { sequence: 1, timestamp: 1_780_000_001, level: "debug", message: "Structured", stage: null }
                    ]
                })
            ).map((line) => line.message)
        ).toEqual(["Structured"])
    })
    test("renders only backend-reported stages with no percentage", () => {
        const markup = renderToStaticMarkup(
            <ConversionProgressSteps
                steps={[
                    { id: "parse", title: "Parse source", status: "completed" },
                    { id: "pack", title: "Package result", status: "running" },
                    { id: "validate", title: "Validate", status: "skipped" }
                ]}
                selectedStage={null}
                onSelectStage={() => {}}
            />
        )
        expect(markup).toContain("1 of 3 stages completed · 1 skipped")
        expect(markup).toContain("In progress")
        expect(markup).toContain("motion-safe:animate-spin")
        expect(markup).not.toContain("aria-valuenow=")
        expect(markup).not.toContain("percent")
    })
    test("does not fabricate stages when telemetry is absent", () => {
        const markup = renderToStaticMarkup(
            <ConversionProgressSteps
                steps={[]}
                selectedStage={null}
                onSelectStage={() => {}}
            />
        )
        expect(markup).toContain("No progress estimate is available")
        expect(markup).not.toContain("Parse source")
    })
})

describe("desktop Jobs rendering", () => {
    test("uses a real empty state and source picker, without sample jobs", () => {
        const markup = renderToStaticMarkup(
            <ConversionJobs
                backend={backend}
                conversions={controller()}
            />
        )
        expect(markup).toContain("Your next corpus starts here")
        expect(markup).toContain("Choose a source file")
        expect(markup).toContain('type="file"')
        expect(markup).toContain(".epub")
        expect(markup).not.toContain("Purchase order")
        expect(markup).not.toContain("Endpoint Security")
    })
    test("shows the app Settings token requirement rather than bypassing auth", () => {
        const markup = renderToStaticMarkup(
            <ConversionJobs
                backend={{ ...backend, authRequired: true }}
                conversions={controller()}
            />
        )
        expect(markup).toContain("Configure a request token in app Settings")
        expect(markup).toContain("authentication is not bypassed")
    })
    test("preserves jobs and logs while the backend is unavailable", () => {
        const markup = renderToStaticMarkup(
            <ConversionJobs
                backend={{ ...backend, state: "failed", error: "Connection refused" }}
                conversions={controller([makeJob({ logs: ["A real backend message"] })])}
            />
        )
        expect(markup).toContain("Connection refused")
        expect(markup).toContain("A real backend message")
        expect(markup).toContain("Sidecar is not ready")
    })
    test("requires both success and download readiness for the result action", () => {
        const queued = renderToStaticMarkup(
            <ConversionJobDetail
                job={makeJob()}
                conversions={controller()}
                backendReady
            />
        )
        const unavailable = renderToStaticMarkup(
            <ConversionJobDetail
                job={makeJob({ status: "succeeded", download_ready: false })}
                conversions={controller()}
                backendReady
            />
        )
        const ready = renderToStaticMarkup(
            <ConversionJobDetail
                job={makeJob({ status: "succeeded", download_ready: true })}
                conversions={controller()}
                backendReady
            />
        )
        const resultButton = (markup: string) =>
            markup.match(/<button\b[^>]*>[\s\S]*?<\/button>/g)?.find((button) => button.includes("Download result")) ??
            ""
        expect(resultButton(queued)).toContain('disabled=""')
        expect(resultButton(unavailable)).toContain('disabled=""')
        expect(resultButton(ready)).not.toContain('disabled=""')
        expect(ready).toContain("source.corpus")
        expect(ready).toContain("Result ready")
    })
    test("disables download when a ready result has no connected sidecar", () => {
        const markup = renderToStaticMarkup(
            <ConversionJobDetail
                job={makeJob({ status: "succeeded", download_ready: true })}
                conversions={controller()}
                backendReady={false}
            />
        )
        expect(markup).toContain('disabled=""')
    })
    test("shows actual job errors and validation payload without hiding them", () => {
        const markup = renderToStaticMarkup(
            <ConversionJobDetail
                job={makeJob({
                    status: "failed",
                    error: "Source XML could not be parsed",
                    validation: { valid: false, errors: ["missing title"] }
                })}
                conversions={controller()}
                backendReady
            />
        )
        expect(markup).toContain("Source XML could not be parsed")
        expect(markup).toContain("Backend validation report")
        expect(markup).toContain("missing title")
        expect(markup).not.toContain("Cancel job")
    })
    test("announces loading and preserves controller errors", () => {
        const markup = renderToStaticMarkup(
            <ConversionJobs
                backend={backend}
                conversions={controller([], { isLoading: true, error: "401: token required" })}
            />
        )
        expect(markup).toContain("Loading jobs…")
        expect(markup).toContain("401: token required")
        expect(markup).toContain('role="alert"')
    })
})
