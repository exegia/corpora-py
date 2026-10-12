import { afterEach, describe, expect, test } from "bun:test"
import { getDefaultStore } from "jotai"
import { uploadAtom, type UploadEntry } from "~/lib/atoms/upload-atom"
import { API_URL } from "~/lib/types/socket"
import {
  deleteUpload,
  initUploadManager,
  publishConversion,
  publishUpload,
  retryUpload,
  saveUpload,
  uploadFile,
} from "./manager"

/**
 * The manual Hugging Face publish contract:
 *
 * - `publishConversion`: one `POST /storage {job_id}` round-trip to
 *   `admin.services.storage_api`, mapped to a `StorageOutcome` without ever
 *   throwing -- a publish problem must annotate the entry, not crash the UI.
 * - `publishUpload`: the user-triggered wrapper -- it only ever runs when
 *   explicitly called (never as part of the conversion pipeline), tracks
 *   the outcome on the entry, and refuses to double-publish.
 */

const realFetch = globalThis.fetch

type RecordedRequest = { url: string; init?: RequestInit }

const stubFetch = (
  respond: () => Response | Promise<Response>
): RecordedRequest[] => {
  const requests: RecordedRequest[] = []
  globalThis.fetch = (async (
    url: string | URL | Request,
    init?: RequestInit
  ) => {
    requests.push({ url: String(url), init })
    return respond()
  }) as typeof fetch
  return requests
}

afterEach(() => {
  globalThis.fetch = realFetch
})

describe("publishConversion", () => {
  test("maps a 201 to a stored outcome with the Hub download URL", async () => {
    const requests = stubFetch(() =>
      Response.json(
        {
          filename: "book.corpus",
          size_bytes: 57609,
          repo_id: "user/archives",
          url: "https://huggingface.co/datasets/user/archives/resolve/main/book.corpus",
        },
        { status: 201 }
      )
    )

    const outcome = await publishConversion("job-123")

    expect(outcome).toEqual({
      status: "stored",
      url: "https://huggingface.co/datasets/user/archives/resolve/main/book.corpus",
      repoId: "user/archives",
      filename: "book.corpus",
      sizeBytes: 57609,
    })

    // The request the server-side router expects: POST /storage {job_id}.
    expect(requests).toHaveLength(1)
    expect(requests[0]!.url).toBe(`${API_URL}/storage`)
    expect(requests[0]!.init?.method).toBe("POST")
    expect(JSON.parse(String(requests[0]!.init?.body))).toEqual({
      job_id: "job-123",
    })
  })

  test("maps an unknown size (null) to undefined, not 0", async () => {
    stubFetch(() =>
      Response.json(
        {
          filename: "book.corpus",
          size_bytes: null,
          repo_id: "user/archives",
          url: "https://huggingface.co/x",
        },
        { status: 201 }
      )
    )
    const outcome = await publishConversion("job-123")
    expect(outcome.status).toBe("stored")
    expect(outcome.sizeBytes).toBeUndefined()
  })

  test("maps a 503 (storage not configured) to skipped with the server's reason", async () => {
    stubFetch(() =>
      Response.json(
        { detail: "Hub storage is not configured: set HF_STORAGE_REPO" },
        { status: 503 }
      )
    )
    const outcome = await publishConversion("job-123")
    expect(outcome.status).toBe("skipped")
    expect(outcome.reasons?.[0]).toContain("HF_STORAGE_REPO")
  })

  test("maps a detail-less error body to a generic reason with the status code", async () => {
    stubFetch(() => new Response("gateway exploded", { status: 502 }))
    const outcome = await publishConversion("job-123")
    expect(outcome.status).toBe("skipped")
    expect(outcome.reasons?.[0]).toBe("Publish request failed (502)")
  })

  test("maps a network failure to skipped instead of throwing", async () => {
    stubFetch(() => {
      throw new TypeError("Unable to connect")
    })
    const outcome = await publishConversion("job-123")
    expect(outcome.status).toBe("skipped")
    expect(outcome.reasons?.[0]).toContain("Unable to connect")
  })
})

describe("publishUpload", () => {
  const store = getDefaultStore()

  const seedEntry = (overrides: Partial<UploadEntry> = {}): string => {
    const id = `test-${Math.random().toString(16).slice(2)}`
    store.set(uploadAtom, (draft) => {
      draft[id] = {
        id,
        name: "book.txt",
        size: 1024,
        type: "text/plain",
        status: "ready",
        progress: 100,
        error: null,
        jobId: "job-123",
        corpusName: "book.corpus",
        ...overrides,
      }
    })
    seededIds.push(id)
    return id
  }

  const seededIds: string[] = []
  afterEach(() => {
    store.set(uploadAtom, (draft) => {
      for (const id of seededIds) delete draft[id]
    })
    seededIds.length = 0
  })

  test("publishes the entry's job and records the stored outcome", async () => {
    const requests = stubFetch(() =>
      Response.json(
        {
          filename: "book.corpus",
          size_bytes: 57609,
          repo_id: "user/archives",
          url: "https://huggingface.co/datasets/user/archives/resolve/main/book.corpus",
        },
        { status: 201 }
      )
    )
    const id = seedEntry()

    await publishUpload(id)

    expect(requests).toHaveLength(1)
    expect(requests[0]!.url).toBe(`${API_URL}/storage`)
    const entry = store.get(uploadAtom)[id]
    expect(entry?.storage?.status).toBe("stored")
    expect(entry?.storage?.repoId).toBe("user/archives")
    // The rest of the entry -- including the local download state -- is
    // untouched by the publish.
    expect(entry?.status).toBe("ready")
  })

  test("records a failed attempt as skipped without touching the entry status", async () => {
    stubFetch(() =>
      Response.json(
        { detail: "Hub storage is not configured: set HF_STORAGE_REPO" },
        { status: 503 }
      )
    )
    const id = seedEntry()

    await publishUpload(id)

    const entry = store.get(uploadAtom)[id]
    expect(entry?.storage?.status).toBe("skipped")
    expect(entry?.storage?.reasons?.[0]).toContain("HF_STORAGE_REPO")
    expect(entry?.status).toBe("ready")
  })

  test("is a no-op for an entry without a server-side job", async () => {
    const requests = stubFetch(() => Response.json({}, { status: 201 }))
    const id = seedEntry({ jobId: undefined })

    await publishUpload(id)

    expect(requests).toHaveLength(0)
    expect(store.get(uploadAtom)[id]?.storage).toBeUndefined()
  })

  test("refuses to double-publish while an attempt is already running", async () => {
    const requests = stubFetch(() => Response.json({}, { status: 201 }))
    const id = seedEntry({ storage: { status: "running" } })

    await publishUpload(id)

    expect(requests).toHaveLength(0)
  })

  test("is a no-op for an unknown id", async () => {
    const requests = stubFetch(() => Response.json({}, { status: 201 }))
    await publishUpload("nope")
    expect(requests).toHaveLength(0)
  })

  test("a cancelled save keeps the converted C-USX entry ready", async () => {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, "window")
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        showSaveFilePicker: async () => {
          throw new DOMException("Cancelled", "AbortError")
        },
      },
    })
    stubFetch(() => new Response(new Blob(["archive bytes"])))
    const id = seedEntry({ corpusName: "book.cusx", outputFormat: "cusx" })
    try {
      await saveUpload(id)
      expect(store.get(uploadAtom)[id]?.status).toBe("ready")
      expect(store.get(uploadAtom)[id]?.corpusName).toBe("book.cusx")
    } finally {
      if (descriptor) Object.defineProperty(globalThis, "window", descriptor)
      else Reflect.deleteProperty(globalThis, "window")
      deleteUpload(id)
    }
  })
})

describe("conversion output choice", () => {
  for (const outputFormat of ["corpus", "cusx"] as const) {
    test(`explicit ${outputFormat} survives retry for Markdown`, async () => {
      const requests = stubFetch(() =>
        Response.json({ detail: "retry fixture" }, { status: 422 })
      )
      const id = uploadFile(new File(["# Heading\n"], "notes.md"), {
        sourceFormat: "markdown",
        outputFormat,
      })
      await new Promise((resolve) => setTimeout(resolve, 0))
      const retried = retryUpload(id)
      await new Promise((resolve) => setTimeout(resolve, 0))
      try {
        expect(retried).toBeDefined()
        expect(requests).toHaveLength(2)
        for (const request of requests) {
          const form = request.init?.body as FormData
          expect(form.get("source_format")).toBe("markdown")
          expect(form.get("output_format")).toBe(outputFormat)
        }
        expect(getDefaultStore().get(uploadAtom)[retried!]?.outputFormat).toBe(
          outputFormat
        )
      } finally {
        deleteUpload(id)
        if (retried) deleteUpload(retried)
      }
    })
  }

  for (const [sourceFormat, outputFormat] of [
    ["plain", "cusx"],
    ["epub", "cusx"],
    ["pdf", "cusx"],
    ["tf_zip", "corpus"],
    ["tei_zip", "corpus"],
  ] as const) {
    test(`${sourceFormat} requests ${outputFormat} without publishing`, async () => {
      const requests = stubFetch(() =>
        Response.json(
          { detail: "test stops after submission" },
          { status: 422 }
        )
      )
      const id = uploadFile(new File(["text"], "fixture.txt"), { sourceFormat })
      await new Promise((resolve) => setTimeout(resolve, 0))
      try {
        expect(requests).toHaveLength(1)
        expect(requests[0].url).toBe(`${API_URL}/convert`)
        const form = requests[0].init?.body as FormData
        expect(form.get("source_format")).toBe(sourceFormat)
        expect(form.get("output_format")).toBe(outputFormat)
      } finally {
        deleteUpload(id)
      }
    })
  }
})


describe("stale conversion recovery", () => {
  const websocketDescriptor = Object.getOwnPropertyDescriptor(globalThis, "WebSocket")
  const windowDescriptor = Object.getOwnPropertyDescriptor(globalThis, "window")
  const storageDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage")
  const ids: string[] = []

  const silentSocket = () => {
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      value: class extends EventTarget {
        close() {}
      },
    })
  }

  afterEach(() => {
    for (const id of ids) deleteUpload(id)
    ids.length = 0
    for (const [key, descriptor] of [
      ["WebSocket", websocketDescriptor],
      ["window", windowDescriptor],
      ["localStorage", storageDescriptor],
    ] as const) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  })

  test("an open silent socket cannot hide a missing server job", async () => {
    silentSocket()
    let requests = 0
    stubFetch(() => {
      requests += 1
      return requests === 1
        ? Response.json({job_id: "gone-job", ws_url: "/convert/gone-job/ws"})
        : Response.json({detail: "Not found"}, {status: 404})
    })
    const id = uploadFile(new File(["text"], "book.txt"))
    ids.push(id)
    await new Promise((resolve) => setTimeout(resolve, 20))
    const entry = getDefaultStore().get(uploadAtom)[id]
    expect(requests).toBe(2)
    expect(entry.status).toBe("error")
    expect(entry.error).toContain("no longer exists")
  })

  test("REST reports the actual terminal validation result without a socket frame", async () => {
    silentSocket()
    let requests = 0
    stubFetch(() => {
      requests += 1
      return requests === 1
        ? Response.json({job_id: "held-job", ws_url: "/convert/held-job/ws"})
        : Response.json({
          status: "failed", logs: ["Comparing source"], last_log: "Comparing source",
          error: "Independent reference required",
          validation: {valid: false, source_reliability: {
            decision: "unscored", score_percent: null, passed: false,
            review_required: true, message: "Independent reference required", mismatches: [],
          }},
        })
    })
    const id = uploadFile(new File(["pdf"], "book.pdf"), {sourceFormat: "pdf"})
    ids.push(id)
    await new Promise((resolve) => setTimeout(resolve, 20))
    const entry = getDefaultStore().get(uploadAtom)[id]
    expect(entry.status).toBe("error")
    expect(entry.validation?.sourceReliability?.decision).toBe("unscored")
    expect(entry.error).toBe("Independent reference required")
  })

  test("reload resumes a job without a saved WebSocket path and reconciles progress", async () => {
    silentSocket()
    const id = "rehydrated-active-job"
    ids.push(id)
    Object.defineProperty(globalThis, "window", {configurable: true, value: {}})
    Object.defineProperty(globalThis, "localStorage", {configurable: true, value: {
      getItem: () => JSON.stringify([{
        id, jobId: "running-job", name: "book.pdf", type: "application/pdf",
        size: 1024, sourceFormat: "pdf", status: "converting", progress: 60, error: null,
      }]),
      setItem: () => {},
    }})
    stubFetch(() => Response.json({
      status: "running", source_format: "pdf", logs: ["PDF OCR: completed 420/925 pages"],
      last_log: "PDF OCR: completed 420/925 pages",
      progress: {completed_pages: 420, total_pages: 925, updated_at: 123},
    }))
    initUploadManager()
    await new Promise((resolve) => setTimeout(resolve, 20))
    const entry = getDefaultStore().get(uploadAtom)[id]
    expect(entry.status).toBe("converting")
    expect(entry.ocrProgress?.completed_pages).toBe(420)
    expect(entry.ocrProgress?.total_pages).toBe(925)
  })
})
