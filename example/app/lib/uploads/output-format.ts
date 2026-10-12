import type { UploadEntry } from "~/lib/atoms/upload-atom"

export type OutputFormat = "corpus" | "ctei"

export const outputFormatForEntry = (entry: UploadEntry): OutputFormat =>
  entry.outputFormat ??
  (entry.corpusName?.endsWith(".ctei") ? "ctei" : "corpus")

export const supportsOutputFormat = (
  sourceFormat: string,
  outputFormat: OutputFormat
): boolean =>
  outputFormat === "corpus" || !["tf_zip", "tei_zip"].includes(sourceFormat)
