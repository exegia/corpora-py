import type { UploadEntry } from "~/lib/atoms/upload-atom"

export type OutputFormat = "corpus" | "cusx" | "ctei"

export const outputFormatForEntry = (entry: UploadEntry): OutputFormat =>
  entry.outputFormat ??
  (entry.corpusName?.endsWith(".ctei")
    ? "ctei"
    : entry.corpusName?.endsWith(".cusx")
      ? "cusx"
      : "corpus")

export const defaultOutputFormat = (sourceFormat: string): OutputFormat =>
  ["tf_zip", "tei_zip"].includes(sourceFormat) ? "corpus" : "cusx"

export const supportsOutputFormat = (
  sourceFormat: string,
  outputFormat: OutputFormat
): boolean =>
  outputFormat === "corpus" || !["tf_zip", "tei_zip"].includes(sourceFormat)
