import { describe, expect, test } from "bun:test"
import { renderToStaticMarkup } from "react-dom/server"
import { ConversionLogs, conversionLogLines, conversionLogsText, filterConversionLogs } from "@/components/conversion-logs"
import { ConversionJobStatus } from "@/components/conversion-job-status"
import { ConversionProgressSteps } from "./c-stepper-21"
import type { ConversionJob } from "@/shared/conversion"

function job(overrides: Partial<ConversionJob> = {}): ConversionJob {
    return {
        id: "telemetry-test", name: "A document", display_name: null, source_format: "epub", output_format: "corpus", status: "running",
        created_at: 1_780_000_000, started_at: 1_780_000_001, finished_at: null, error: null,
        events: [], logs: [], last_log: null, steps: [], validation: null, result_filename: "document.corpus", download_ready: false,
        ...overrides,
    }
}

describe("conversion telemetry presentation", () => {
    test("uses reported stage states rather than estimating progress", () => {
        const markup = renderToStaticMarkup(<ConversionProgressSteps steps={[
            { id: "parse", title: "Parse", status: "completed" },
            { id: "pack", title: "Package", status: "running" },
            { id: "validate", title: "Validation", status: "skipped" },
        ]} selectedStage="pack" onSelectStage={() => {}} />)
        expect(markup).toContain("1 of 3 stages completed · 1 skipped")
        expect(markup).toContain("In progress")
        expect(markup).toContain('aria-pressed="true"')
        expect(markup).toContain("motion-safe:animate-spin")
        expect(markup).not.toContain('aria-valuenow=')
    })
    test("does not fabricate stages before the backend reports them", () => {
        const markup = renderToStaticMarkup(<ConversionProgressSteps steps={[]} selectedStage={null} onSelectStage={() => {}} />)
        expect(markup).toContain("Waiting for reported stages")
        expect(markup).toContain("No progress estimate is available")
        expect(markup).not.toContain("Parse")
    })
    test("shows failed and skipped stages without treating them as completed", () => {
        const markup = renderToStaticMarkup(<ConversionProgressSteps steps={[{ id: "parse", title: "Parse", status: "failed" }, { id: "pack", title: "Package", status: "skipped" }]} selectedStage={null} onSelectStage={() => {}} />)
        expect(markup).toContain("0 of 2 stages completed · 1 skipped")
        expect(markup).toContain("Failed")
        expect(markup).toContain("Skipped")
        expect(markup).not.toContain("motion-safe:animate-spin")
    })
    test("renders all real job status labels with a static cue", () => {
        for (const [status, label] of [["queued", "Queued"], ["running", "Running"], ["succeeded", "Succeeded"], ["failed", "Failed"]] as const) {
            expect(renderToStaticMarkup(<ConversionJobStatus status={status} />)).toContain(label)
        }
    })
    test("combines levels, stage and case-insensitive log search", () => {
        const lines = conversionLogLines(job({ events: [
            { sequence: 1, timestamp: 1_780_000_001, level: "info", message: "Parsing chapter", stage: "parse" },
            { sequence: 2, timestamp: 1_780_000_002, level: "warning", message: "Missing metadata", stage: "parse" },
            { sequence: 3, timestamp: 1_780_000_003, level: "error", message: "Missing archive", stage: "package" },
        ] }))
        expect(filterConversionLogs(lines, ["warning", "error"], " MISSING ", "parse").map(line => line.message)).toEqual(["Missing metadata"])
        expect(filterConversionLogs(lines, [], "", null)).toEqual([])
        expect(conversionLogsText(lines)).toContain(new Date(1_780_000_002 * 1000).toISOString())
        expect(conversionLogsText(lines)).toContain("[warning] [parse] Missing metadata")
    })
    test("prefers structured events over duplicate legacy strings", () => {
        const lines = conversionLogLines(job({ logs: ["Duplicate"], events: [{ sequence: 1, timestamp: 1_780_000_001, level: "debug", message: "Actual event", stage: null }] }))
        expect(lines).toHaveLength(1)
        expect(lines[0].message).toBe("Actual event")
    })
    test("leaves legacy strings unclassified instead of guessing level or time", () => {
        const lines = conversionLogLines(job({ logs: ["ERROR in a document title is not structured metadata"] }))
        expect(lines[0].level).toBe("unclassified")
        expect(lines[0].timestamp).toBeNull()
        expect(lines[0].stage).toBeNull()
        expect(filterConversionLogs(lines, ["error"], "", null)).toEqual([])
        expect(conversionLogsText(lines)).toStartWith("[unclassified]")
    })
    test("renders job-specific logs, level toggles and searchable region", () => {
        const markup = renderToStaticMarkup(<ConversionLogs job={job({ events: [{ sequence: 1, timestamp: 1_780_000_001, level: "warning", message: "A real warning", stage: "parse" }] })} stage={null} onClearStage={() => {}} />)
        expect(markup).toContain("A real warning")
        expect(markup).toContain('role="log"')
        expect(markup).toContain('aria-live="off"')
        expect(markup).toContain('aria-label="Log levels"')
        expect(markup).toContain('type="search"')
        expect(markup).toContain("Copy visible logs")
    })
    test("announces empty logs truthfully and allows clearing a stage filter", () => {
        const empty = renderToStaticMarkup(<ConversionLogs job={job()} stage={null} onClearStage={() => {}} />)
        expect(empty).toContain("No logs reported yet")
        const filtered = renderToStaticMarkup(<ConversionLogs job={job({ logs: ["Legacy message"] })} stage="parse" onClearStage={() => {}} />)
        expect(filtered).toContain("No log lines match these filters")
        expect(filtered).toContain("Show all stages")
        expect(filtered).toContain("Unclassified logs have no reported level, stage, or timestamp")
    })
})
