import { expect, test } from "bun:test"
import { getDefaultStore } from "jotai"
import { uploadAtom, type UploadEntry } from "~/lib/atoms/upload-atom"
import { API_URL } from "~/lib/types/socket"
import { deleteUpload, uploadFile } from "./manager"

/**
 * Live integration test of the requirement: once upload/conversion/
 * validation are done, the archive is published to Hugging Face and the Hub
 * download URL comes back on the entry, with the publish visible in the
 * tracked state. Runs the REAL manager flow (fetch + WebSocket + jotai, no
 * mocks) against a locally running `corpora-api`; skipped automatically
 * when the server (or its Hub storage config) isn't up, so `bun test`
 * stays green offline.
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
  "converted corpus is published to Hugging Face with a download URL",
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

      // The requirement under test: the finished archive landed on the Hub
      // and the entry carries its download URL.
      expect(entry.storage?.status).toBe("stored")
      expect(entry.storage?.filename).toBe(`${JOB_NAME}.corpus`)
      expect(entry.storage?.repoId).toBeTruthy()
      expect(entry.storage?.url).toMatch(
        new RegExp(
          `^https://huggingface\\.co/.+/resolve/main/${JOB_NAME}\\.corpus$`
        )
      )
      expect(entry.storage?.sizeBytes).toBeGreaterThan(0)

      // The publish is observable in the logged pipeline state the console
      // renders from (server logs + the storage outcome itself).
      expect(entry.logs?.length).toBeGreaterThan(0)

      // And the URL the server returned matches what GET /storage lists.
      const listed = (await fetch(`${API_URL}/storage`).then((response) =>
        response.json()
      )) as Array<{ filename: string; url: string }>
      const stored = listed.find(
        (candidate) => candidate.filename === `${JOB_NAME}.corpus`
      )
      expect(stored?.url).toBe(entry.storage?.url)
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
