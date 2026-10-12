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

describe("archive validation counts", () => {
  test("shows document statistics for C-USX without graph statistics", () => {
    const entry = baseEntry({
      validation: {
        status: "valid",
        stats: {
          documents: 41,
          assets: 19,
          characters: 394317,
          units: 20946,
        },
      },
    })
    const text = stageById(entry, "validation")
      .logs.map((line) => line.text)
      .join("\n")
    expect(text).toContain("41 documents, 19 assets, 394,317 characters")
    expect(text).not.toContain("slots")
    expect(text).not.toContain(".tf")
  })

  test("retains graph statistics for Text-Fabric archives", () => {
    const entry = baseEntry({
      validation: {
        status: "valid",
        stats: {
          max_slot: 11,
          node_types: 2,
          node_features: 3,
          edge_features: 4,
        },
      },
    })
    const text = stageById(entry, "validation")
      .logs.map((line) => line.text)
      .join("\n")
    expect(text).toContain("11 slots, 2 node types, 7 features")
    expect(text).not.toContain("documents")
  })
})

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


describe("PDF source reliability", () => {
  const entry = (score: number, passed: boolean, review: boolean) => baseEntry({
    sourceFormat: "pdf", status: passed ? "ready" : "error",
    validation: { status: passed ? "valid" : "invalid", sourceReliability: {
      score_percent: score, decision: passed ? review ? "review" : "pass" : "loss",
      passed, review_required: review, message: "Independent comparison.",
      mismatches: [{page_number: 1, expected: "שָׁלוֹם", actual: "שלום"}],
    } },
  })
  test("review passes show a warning and literal mismatches", () => {
    const stage = stageById(entry(75, true, true), "validation")
    expect(stage.state).toBe("warning")
    expect(stage.logs.map(line => line.text).join("\n")).toContain("שָׁלוֹם")
  })
  test("loss holds acceptance", () => {
    const loss = entry(49, false, false)
    const stage = stageById(loss, "validation")
    expect(stage.state).toBe("failed")
    expect(stageById(loss, "converting").state).toBe("completed")
    expect(stage.logs.map(line => line.text).join("\n")).toContain("Acceptance is held")
  })
  test("rounding cannot move a score into another decision band", () => {
    for (const [score, passed] of [[49.9999, false], [90.0001, true]] as const) {
      const logs = stageById(entry(score, passed, false), "validation").logs
      expect(logs.map(line => line.text).join("\n")).toContain(`${score}%`)
    }
  })
})
