import { afterEach, describe, expect, test } from "bun:test"
import { getDefaultStore } from "jotai"
import { uploadAtom, type UploadEntry } from "~/lib/atoms/upload-atom"
import { API_URL } from "~/lib/types/socket"
import { publishConversion, publishUpload } from "./manager"

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
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
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
})
