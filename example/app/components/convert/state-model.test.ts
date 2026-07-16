import { describe, expect, test } from "bun:test"
import type { StorageOutcome, UploadEntry } from "~/lib/atoms/upload-atom"
import { deriveStages, deriveView } from "./state-model"

/**
 * Requirements under test (see README.md in this directory):
 * publishing to the Hugging Face Hub is a MANUAL step on a completed
 * conversion (`POST /storage` via `publishUpload`), the publish process
 * shows up in the console logs, the Hub download URL is surfaced, and a
 * failed publish never blocks the local download/save flow.
 */

const baseEntry = (overrides: Partial<UploadEntry> = {}): UploadEntry => ({
  id: "test-id",
  name: "book.txt",
  size: 1024,
  type: "text/plain",
  status: "ready",
  progress: 100,
  error: null,
  sourceFormat: "plain",
  jobId: "job-123",
  logs: ["Parsing plain text…", "Packaging .corpus archive…"],
  validation: { status: "valid", stats: { max_slot: 11 } },
  ...overrides,
})

const stageById = (entry: UploadEntry, id: string) => {
  const stage = deriveStages(entry).find((candidate) => candidate.id === id)
  if (!stage) throw new Error(`No stage ${id}`)
  return stage
}

const STORED: StorageOutcome = {
  status: "stored",
  url: "https://huggingface.co/datasets/user/archives/resolve/main/book.corpus",
  repoId: "user/archives",
  filename: "book.corpus",
  sizeBytes: 57609,
}

describe("manual publish in flight", () => {
  const entry = baseEntry({ storage: { status: "running" } })

  test("keeps the completed view — publishing is post-pipeline", () => {
    expect(deriveView(entry)).toBe("completed")
  })

  test("marks the storage stage active while the upload to the Hub runs", () => {
    const stage = stageById(entry, "storage")
    expect(stage.state).toBe("active")
    expect(stage.logs.map((line) => line.text).join("\n")).toContain(
      "POST /storage"
    )
  })

  test("leaves the finished pipeline stages completed", () => {
    expect(stageById(entry, "converting").state).toBe("completed")
    expect(stageById(entry, "validation").state).toBe("completed")
    expect(stageById(entry, "download").state).toBe("completed")
  })
})

describe("stored outcome", () => {
  const entry = baseEntry({ storage: STORED })

  test("completes the stage", () => {
    expect(stageById(entry, "storage").state).toBe("completed")
  })

  test("logs the archive, the repo, and the Hub download URL", () => {
    const text = stageById(entry, "storage")
      .logs.map((line) => line.text)
      .join("\n")
    expect(text).toContain("book.corpus")
    expect(text).toContain("user/archives")
    expect(text).toContain(STORED.url!)
  })

  test("keeps the completed view and the download stage intact", () => {
    expect(deriveView(entry)).toBe("completed")
    expect(stageById(entry, "download").state).toBe("completed")
  })
})

describe("failed publish never blocks the local flow", () => {
  const entry = baseEntry({
    storage: {
      status: "skipped",
      reasons: ["Hub storage is not configured: set HF_STORAGE_REPO"],
    },
  })

  test("marks the stage as a warning (not failed) with the reason and a retry hint", () => {
    const stage = stageById(entry, "storage")
    expect(stage.state).toBe("warning")
    const text = stage.logs.map((line) => line.text).join("\n")
    expect(text).toContain("HF_STORAGE_REPO")
    expect(text).toContain("still downloadable")
    expect(text).toContain("retry")
  })

  test("the run still derives as completed and downloadable", () => {
    expect(deriveView(entry)).toBe("completed")
    expect(stageById(entry, "download").state).toBe("completed")
  })
})

describe("entries the user has not published", () => {
  test("stay pending with a hint at the manual action, not a warning", () => {
    const entry = baseEntry({ status: "success", storage: undefined })
    const stage = stageById(entry, "storage")
    expect(stage.state).toBe("pending")
    expect(stage.logs.map((line) => line.text).join("\n")).toContain(
      "Publish to Hugging Face"
    )
  })

  test("stay pending and silent while the pipeline is still running", () => {
    const entry = baseEntry({ status: "converting", storage: undefined })
    expect(stageById(entry, "storage").state).toBe("pending")
    expect(stageById(entry, "storage").logs).toHaveLength(0)
  })
})

describe("regressions around the storage stage", () => {
  test("stage order places the manual publish after download", () => {
    const ids = deriveStages(baseEntry()).map((stage) => stage.id)
    expect(ids).toEqual([
      "received",
      "validated",
      "upload",
      "queued",
      "converting",
      "validation",
      "download",
      "storage",
    ])
  })

  test("a conversion failure leaves the storage stage pending", () => {
    const entry = baseEntry({
      status: "error",
      error: "boom",
      storage: undefined,
      validation: undefined,
    })
    expect(deriveView(entry)).toBe("failed")
    expect(stageById(entry, "converting").state).toBe("failed")
    expect(stageById(entry, "storage").state).toBe("pending")
  })

  test("an invalid corpus can still be published (verdict does not gate storage)", () => {
    const entry = baseEntry({
      validation: { status: "invalid", reasons: ["stats mismatch"] },
      storage: STORED,
    })
    expect(stageById(entry, "validation").state).toBe("failed")
    expect(stageById(entry, "storage").state).toBe("completed")
  })
})
