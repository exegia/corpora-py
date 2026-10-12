import { afterEach, expect, test } from "bun:test"
import { saveCorpusFile } from "./save-corpus-file"

const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window")
afterEach(() => {
  if (originalWindow)
    Object.defineProperty(globalThis, "window", originalWindow)
  else Reflect.deleteProperty(globalThis, "window")
})

const usePicker = (picker: unknown) =>
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { showSaveFilePicker: picker },
  })

for (const extension of ["corpus", "cusx"]) {
  test(`native save writes the exact blob with the .${extension} extension`, async () => {
    const blob = new Blob(["archive bytes"])
    const calls: string[] = []
    let options: any
    usePicker(async (received: unknown) => {
      options = received
      return {
        createWritable: async () => ({
          write: async (received: Blob) => {
            expect(received).toBe(blob)
            calls.push("write")
          },
          close: async () => {
            calls.push("close")
          },
        }),
      }
    })
    expect(await saveCorpusFile(`book.${extension}`, blob)).toBe(true)
    expect(options.suggestedName).toBe(`book.${extension}`)
    expect(options.types[0].accept["application/zip"]).toEqual([
      `.${extension}`,
    ])
    expect(calls).toEqual(["write", "close"])
  })
}

test("cancelled native save is not reported as saved", async () => {
  usePicker(async () => {
    throw new DOMException("Cancelled", "AbortError")
  })
  expect(await saveCorpusFile("book.cusx", new Blob())).toBe(false)
})

test("native write failure remains an error", async () => {
  usePicker(async () => ({
    createWritable: async () => ({
      write: async () => {
        throw new Error("Disk full")
      },
      close: async () => {},
    }),
  }))
  await expect(saveCorpusFile("book.corpus", new Blob())).rejects.toThrow("Disk full")
})
