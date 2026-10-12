import { expect, test } from "bun:test"
import { detectSourceFormat } from "./source-format"

test("Markdown and generic XML retain distinct source formats", () => {
  expect(detectSourceFormat("notes.MD")).toBe("markdown")
  expect(detectSourceFormat("notes.markdown")).toBe("markdown")
  expect(detectSourceFormat("catalog.xml")).toBe("xml")
  expect(detectSourceFormat("edition.tei")).toBe("tei")
  expect(() => detectSourceFormat("unknown.bin")).toThrow("Can't auto-detect")
})
