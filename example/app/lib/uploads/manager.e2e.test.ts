import { expect, test } from "bun:test"
import { getDefaultStore } from "jotai"
import { uploadAtom, type UploadEntry } from "~/lib/atoms/upload-atom"
import { API_URL } from "~/lib/types/socket"
import { deleteUpload, publishUpload, uploadFile } from "./manager"

/**
 * Live integration test of the requirement: the conversion pipeline
 * finishes WITHOUT touching Hugging Face, and only an explicit
 * `publishUpload` call (the "Publish to Hugging Face" button) pushes the
 * archive to the Hub and puts the download URL on the entry. Runs the REAL
 * manager flow (fetch + WebSocket + jotai, no mocks) against a locally
 * running `corpora-api`; skipped automatically when the server (or its Hub
 * storage config) isn't up, so `bun test` stays green offline.
 */

const serverUp = await fetch(`${API_URL}/health`)
  .then((response) => response.ok)
  .catch(() => false)

// Distinguish "storage never configured" (503) from a usable Hub setup so
// an unconfigured local server skips instead of failing the assertion.
const storageUp = serverUp
  ? await fetch(`${API_URL}/storage`).then((response) => response.ok)
  : false

const JOB_NAME = "hf-e2e-manager-test"

const waitForTerminal = async (id: string): Promise<UploadEntry> => {
  const store = getDefaultStore()
  const deadline = Date.now() + 120_000
  for (;;) {
    const entry = store.get(uploadAtom)[id]
    if (
      entry &&
      (entry.status === "ready" ||
        entry.status === "success" ||
        entry.status === "error")
    ) {
      return entry
    }
    if (Date.now() > deadline) throw new Error("Timed out waiting for job")
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
}

test.skipIf(!serverUp || !storageUp)(
  "converted corpus is only published to Hugging Face on explicit request",
  async () => {
    const file = new File(
      [
        "Hello from the example app manager e2e run.\n\n" +
          "A second paragraph so the plain-text parser has two units.\n",
      ],
      `${JOB_NAME}.txt`,
      { type: "text/plain" }
    )

    const id = await uploadFile(file, { name: JOB_NAME })
    try {
      const entry = await waitForTerminal(id)

      // Conversion + validation succeeded and the archive was downloaded.
      expect(entry.status).toBe("ready")
      expect(entry.error).toBeNull()
      expect(entry.validation?.status).toBe("valid")
      expect(entry.corpusName).toBe(`${JOB_NAME}.corpus`)

      // The requirement under test, part 1: finishing the pipeline did NOT
      // publish anything -- the Hub push is manual.
      expect(entry.storage).toBeUndefined()

      // Part 2: the explicit publish (what the "Publish to Hugging Face"
      // button calls) pushes the archive and records the download URL.
      await publishUpload(id)
      const published = getDefaultStore().get(uploadAtom)[id]!
      expect(published.storage?.status).toBe("stored")
      expect(published.storage?.filename).toBe(`${JOB_NAME}.corpus`)
      expect(published.storage?.repoId).toBeTruthy()
      expect(published.storage?.url).toMatch(
        new RegExp(
          `^https://huggingface\\.co/.+/resolve/main/${JOB_NAME}\\.corpus$`
        )
      )
      expect(published.storage?.sizeBytes).toBeGreaterThan(0)

      // The publish is observable in the logged pipeline state the console
      // renders from (server logs + the storage outcome itself).
      expect(published.logs?.length).toBeGreaterThan(0)

      // And the URL the server returned matches what GET /storage lists.
      const listed = (await fetch(`${API_URL}/storage`).then((response) =>
        response.json()
      )) as Array<{ filename: string; url: string }>
      const stored = listed.find(
        (candidate) => candidate.filename === `${JOB_NAME}.corpus`
      )
      expect(stored?.url).toBe(published.storage?.url)
    } finally {
      // Leave neither the Hub artifact nor local tracking state behind.
      await fetch(`${API_URL}/storage/${JOB_NAME}.corpus`, {
        method: "DELETE",
      }).catch(() => undefined)
      deleteUpload(id)
    }
  },
  150_000
)
