import { useMemo, useState } from "react"
import { Check, Copy, Terminal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"
import type { ConversionJob } from "@/shared/conversion"

export type ConversionLogLevel = ConversionJob["events"][number]["level"] | "unclassified"
export interface ConversionLogLine {
    key: string
    timestamp: number | null
    level: ConversionLogLevel
    message: string
    stage: string | null
}
const levels: ConversionLogLevel[] = ["debug", "info", "warning", "error", "unclassified"]

export function conversionLogLines(job: ConversionJob): ConversionLogLine[] {
    if (job.events.length)
        return job.events.map((event) => ({
            key: `${job.id}:${event.sequence}`,
            timestamp: event.timestamp,
            level: event.level,
            message: event.message,
            stage: event.stage
        }))
    // Older backends expose strings without trustworthy level, stage or timestamp metadata.
    return job.logs.map((message, index) => ({
        key: `${job.id}:legacy:${index}`,
        timestamp: null,
        level: "unclassified",
        message,
        stage: null
    }))
}

export function filterConversionLogs(
    lines: ConversionLogLine[],
    selectedLevels: readonly string[],
    search: string,
    stage: string | null
): ConversionLogLine[] {
    const query = search.trim().toLocaleLowerCase()
    return lines.filter(
        (line) =>
            selectedLevels.includes(line.level) &&
            (!stage || line.stage === stage) &&
            (!query || `${line.level} ${line.stage ?? ""} ${line.message}`.toLocaleLowerCase().includes(query))
    )
}

export function conversionLogsText(lines: ConversionLogLine[]): string {
    return lines
        .map((line) =>
            [
                line.timestamp === null ? "" : new Date(line.timestamp * 1000).toISOString(),
                `[${line.level}]`,
                line.stage ? `[${line.stage}]` : "",
                line.message
            ]
                .filter(Boolean)
                .join(" ")
        )
        .join("\n")
}

export function ConversionLogs({
    job,
    stage,
    onClearStage
}: {
    job: ConversionJob
    stage: string | null
    onClearStage: () => void
}) {
    const [search, setSearch] = useState("")
    const [selectedLevels, setSelectedLevels] = useState<string[]>(levels)
    const [copyState, setCopyState] = useState<"idle" | "copying" | "copied">("idle")
    const [copyError, setCopyError] = useState<string | null>(null)
    const [copiedText, setCopiedText] = useState<string | null>(null)
    const lines = useMemo(() => conversionLogLines(job), [job])
    const filtered = useMemo(
        () => filterConversionLogs(lines, selectedLevels, search, stage),
        [lines, selectedLevels, search, stage]
    )
    const visibleText = useMemo(() => conversionLogsText(filtered), [filtered])
    const showCopied = copyState === "copied" && copiedText === visibleText
    const hasLegacy = lines.some((line) => line.level === "unclassified")

    async function copyLogs() {
        if (copyState === "copying") return
        setCopyState("copying")
        setCopyError(null)
        try {
            await navigator.clipboard.writeText(visibleText)
            setCopiedText(visibleText)
            setCopyState("copied")
        } catch {
            setCopyError("Clipboard access is unavailable. You can select and copy the log text below.")
            setCopyState("idle")
        }
    }

    return (
        <section
            aria-labelledby="conversion-logs-heading"
            className="flex min-w-0 flex-col gap-3">
            <header className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Terminal
                        className="size-4 text-muted-foreground"
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                    <h3
                        id="conversion-logs-heading"
                        className="text-sm font-semibold">
                        Job logs
                    </h3>
                    <span className="text-xs tabular-nums text-muted-foreground">
                        {filtered.length} / {lines.length}
                    </span>
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={!filtered.length || copyState === "copying"}
                    onClick={() => void copyLogs()}>
                    {showCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                    {showCopied ? "Copied" : "Copy visible logs"}
                </Button>
            </header>
            <div className="flex flex-wrap items-end gap-3">
                <Field className="min-w-40 flex-1">
                    <FieldLabel className="sr-only">Search conversion logs</FieldLabel>
                    <Input
                        type="search"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search messages or stages…"
                    />
                </Field>
                <ToggleGroup
                    multiple
                    value={selectedLevels}
                    onValueChange={({ value }) => setSelectedLevels(value)}
                    size="sm"
                    spacing={1}
                    className="flex-wrap"
                    aria-label="Log levels">
                    {levels
                        .filter((level) => level !== "unclassified" || hasLegacy)
                        .map((level) => (
                            <ToggleGroupItem
                                type="button"
                                key={level}
                                value={level}
                                aria-label={`Show ${level} logs`}>
                                {level === "unclassified"
                                    ? "Unclassified"
                                    : level === "warning"
                                      ? "Warn"
                                      : level[0].toUpperCase() + level.slice(1)}
                            </ToggleGroupItem>
                        ))}
                </ToggleGroup>
            </div>
            {stage && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="min-w-0 break-all">
                        Stage: {job.steps.find((step) => step.id === stage)?.title ?? stage}
                    </span>
                    <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        onClick={onClearStage}>
                        Show all stages
                    </Button>
                </div>
            )}
            <div
                role="log"
                aria-label={`Logs for ${job.display_name || job.name}`}
                aria-live="off"
                tabIndex={0}
                className="max-h-80 min-h-36 overflow-auto rounded-xl border border-border bg-muted/30 p-3 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {filtered.length ? (
                    <ol className="flex flex-col gap-1">
                        {filtered.map((line) => (
                            <li
                                key={line.key}
                                className="grid grid-cols-[auto_4.5rem_minmax(0,1fr)] items-baseline gap-x-3 rounded-sm py-1">
                                <span className="tabular-nums text-muted-foreground">
                                    {line.timestamp === null ? (
                                        "—"
                                    ) : (
                                        <time dateTime={new Date(line.timestamp * 1000).toISOString()}>
                                            {new Date(line.timestamp * 1000).toLocaleTimeString(undefined, {
                                                hour12: false
                                            })}
                                        </time>
                                    )}
                                </span>
                                <span
                                    className={cn(
                                        "uppercase text-muted-foreground",
                                        line.level === "error" && "text-destructive-foreground",
                                        line.level === "warning" && "text-warning-foreground"
                                    )}>
                                    {line.level === "unclassified" ? "legacy" : line.level}
                                </span>
                                <span className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                                    {line.stage && <span className="me-2 text-muted-foreground">[{line.stage}]</span>}
                                    {line.message}
                                </span>
                            </li>
                        ))}
                    </ol>
                ) : (
                    <p className="py-8 text-center font-sans text-sm text-muted-foreground">
                        {lines.length ? "No log lines match these filters." : "No logs reported yet."}
                    </p>
                )}
            </div>
            {hasLegacy && (
                <p className="text-xs text-muted-foreground">
                    Unclassified logs have no reported level, stage, or timestamp.
                </p>
            )}
            <p
                role="status"
                className={cn("text-xs", copyError ? "text-destructive-foreground" : "sr-only")}>
                {copyError ?? (showCopied ? "Visible log lines copied to clipboard." : "")}
            </p>
        </section>
    )
}
