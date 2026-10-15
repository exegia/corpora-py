import type { ConversionJob, ConversionOptions, CorpusCategory, SourceFormat } from "./conversion"

export type Theme = "system" | "light" | "dark"
export type ResolvedTheme = Exclude<Theme, "system">
export type ConversionDraft = Omit<ConversionOptions, "source_format" | "category"> & {
    source_format: SourceFormat | ""
    category: CorpusCategory | ""
}
export type ConversionReviewStep = 0 | 1 | 2
export type ConversionStatusFilter = ConversionJob["status"] | "all"
export interface ConversionDetailState {
    stage: string | null
    downloading: boolean
    downloadError: string | null
}
export type ConversionLogLevel = ConversionJob["events"][number]["level"] | "unclassified"
export interface ConversionLogState {
    search: string
    selectedLevels: string[]
    copyState: "idle" | "copying" | "copied"
    copyError: string | null
    copiedText: string | null
}
