import { afterEach, expect, test } from "bun:test"
import { saveCorpusFile } from "./save-corpus-file"

const originalWindow = globalThis.window
afterEach(() => {
  if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window")
  else globalThis.window = originalWindow
})

for (const extension of ["ctei", "corpus"]) {
  test(`native save uses the .${extension} filename and file filter`, async () => {
    let options: unknown
    let written: Blob | undefined
    let closed = false
    globalThis.window = {
      showSaveFilePicker: async (value: unknown) => {
        options = value
        return { createWritable: async () => ({
          write: async (blob: Blob) => { written = blob },
          close: async () => { closed = true },
        }) }
      },
    } as unknown as Window & typeof globalThis
    const blob = new Blob(["fixture bytes"], { type: "application/zip" })
    await saveCorpusFile(`book.${extension}`, blob)
    expect(options).toEqual({ suggestedName: `book.${extension}`, types: [{
      description: extension === "ctei" ? "TEI archive" : "Corpus archive",
      accept: { "application/zip": [`.${extension}`] },
    }] })
    expect(written).toBe(blob)
    expect(closed).toBe(true)
  })
}
