import { afterEach, describe, expect, test } from "bun:test"
import { getDefaultStore } from "jotai"
import { uploadAtom, type UploadEntry } from "~/lib/atoms/upload-atom"
import { API_URL } from "~/lib/types/socket"
import {
  deleteUpload,
  publishConversion,
  publishUpload,
  retryUpload,
  uploadFile,
  validateConversion,
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

describe("conversion output selection", () => {
  test("sends .ctei and retains it when retrying the failed upload", async () => {
    const requests = stubFetch(() =>
      Response.json({ detail: "Retry fixture" }, { status: 503 })
    )
    const file = new File(["λόγος"], "book.txt", { type: "text/plain" })
    const id = uploadFile(file, { outputFormat: "ctei" })
    await Bun.sleep(0)
    expect(getDefaultStore().get(uploadAtom)[id]?.outputFormat).toBe("ctei")
    expect(getDefaultStore().get(uploadAtom)[id]?.status).toBe("error")
    const retried = retryUpload(id)!
    await Bun.sleep(0)
    expect(requests).toHaveLength(2)
    for (const request of requests) {
      const form = request.init!.body as FormData
      expect(form.get("output_format")).toBe("ctei")
      expect(form.get("source_format")).toBe("plain")
    }
    expect(getDefaultStore().get(uploadAtom)[retried]?.outputFormat).toBe(
      "ctei"
    )
    deleteUpload(retried)
  })

  test("sends the selected .corpus output", async () => {
    const requests = stubFetch(() =>
      Response.json({ detail: "Fixture" }, { status: 503 })
    )
    const id = uploadFile(new File(["Text"], "book.txt"), {
      outputFormat: "corpus",
    })
    await Bun.sleep(0)
    expect((requests[0]!.init!.body as FormData).get("output_format")).toBe(
      "corpus"
    )
    deleteUpload(id)
  })

  test("rejects a multi-document TEI ZIP before sending a .ctei request", async () => {
    const requests = stubFetch(() => Response.json({}))
    const id = uploadFile(new File(["ZIP"], "book.zip"), {
      sourceFormat: "tei_zip",
      outputFormat: "ctei",
    })
    await Bun.sleep(0)
    expect(requests).toHaveLength(0)
    expect(getDefaultStore().get(uploadAtom)[id]?.error).toContain(
      "individual source document"
    )
    deleteUpload(id)
  })
})

describe("completed job validation", () => {
  test("uses the .corpus job verdict without a second validation request", async () => {
    const requests = stubFetch(() => new Response(null, { status: 409 }))
    const outcome = await validateConversion("job-123", "corpus", {
      valid: true,
      stats: { max_slot: 19 },
    })
    expect(outcome.status).toBe("valid")
    expect(outcome.stats?.max_slot).toBe(19)
    expect(requests).toHaveLength(0)
  })

  test("preserves an invalid .ctei verdict and source verification status", async () => {
    const requests = stubFetch(() => Response.json({}))
    const outcome = await validateConversion("job-123", "ctei", {
      valid: false,
      reasons: ["Broken reference"],
      source_verified: false,
    })
    expect(outcome.status).toBe("invalid")
    expect(outcome.reasons).toEqual(["Broken reference"])
    expect(outcome.sourceVerified).toBe(false)
    expect(requests).toHaveLength(0)
  })

  test("falls back to POST /validate for an older .corpus response", async () => {
    const requests = stubFetch(() =>
      Response.json({ valid: true, stats: { max_slot: 19 } })
    )
    expect((await validateConversion("job-123")).status).toBe("valid")
    expect(requests).toHaveLength(1)
    expect(requests[0]!.url).toBe(`${API_URL}/validate`)
    expect(JSON.parse(String(requests[0]!.init?.body))).toEqual({
      job_id: "job-123",
    })
  })

  test("never sends a .ctei job to the corpus-only validator", async () => {
    const requests = stubFetch(() => Response.json({}))
    const outcome = await validateConversion("job-123", "ctei")
    expect(outcome.status).toBe("skipped")
    expect(outcome.reasons?.[0]).toContain(
      "did not return TEI archive validation"
    )
    expect(requests).toHaveLength(0)
  })
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
})

describe("conversion output choice", () => {
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
