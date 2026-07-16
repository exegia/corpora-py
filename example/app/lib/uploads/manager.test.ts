import { afterEach, describe, expect, test } from "bun:test"
import { API_URL } from "~/lib/types/socket"
import { publishConversion } from "./manager"

/**
 * `publishConversion` contract: one `POST /storage {job_id}` round-trip to
 * `admin.services.storage_api`, mapped to a `StorageOutcome` without ever
 * throwing -- a publish problem must annotate the conversion, not break the
 * job-succeeded handler that also drives the local download.
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
