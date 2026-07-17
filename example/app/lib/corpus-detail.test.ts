import { describe, expect, test } from "bun:test"
import {
  buildManifestPatch,
  EDITABLE_MANIFEST_FIELDS,
  filenameToId,
  idToFilename,
  manifestFieldLabel,
  pickerOptions,
  type EditableManifestField,
  type IndexSections,
  type Manifest,
} from "~/lib/corpus-detail"

/**
 * Pure-helper unit tests for the corpus-detail client (mirrors the pure-only
 * style of `components/convert/state-model.test.ts`). The async fetchers touch
 * `API_URL` + the network and are intentionally not exercised here.
 */

// ── id <-> filename ──────────────────────────────────────────────────────────

describe("idToFilename / filenameToId", () => {
  test("idToFilename appends .corpus", () => {
    expect(idToFilename("BHSA")).toBe("BHSA.corpus")
  })

  test("filenameToId strips a trailing .corpus", () => {
    expect(filenameToId("BHSA.corpus")).toBe("BHSA")
  })

  test("round-trips id -> filename -> id", () => {
    for (const id of ["BHSA", "my corpus", "a.corpus"]) {
      expect(filenameToId(idToFilename(id))).toBe(id)
    }
  })

  test("strips the suffix case-insensitively", () => {
    expect(filenameToId("Genesis.CORPUS")).toBe("Genesis")
    expect(filenameToId("Genesis.Corpus")).toBe("Genesis")
  })

  test("only strips the anchored trailing suffix, not mid-string matches", () => {
    // ".corpus" in the middle stays put; only the final one is removed.
    expect(filenameToId("my.corpus.corpus")).toBe("my.corpus")
    // Not at the end at all -> unchanged.
    expect(filenameToId("a.corpus.zip")).toBe("a.corpus.zip")
    expect(filenameToId("corpusless.txt")).toBe("corpusless.txt")
  })
})

// ── buildManifestPatch ───────────────────────────────────────────────────────

const draftOf = (
  overrides: Partial<Record<EditableManifestField, string>> = {}
): Record<EditableManifestField, string> => {
  const draft = {} as Record<EditableManifestField, string>
  for (const field of EDITABLE_MANIFEST_FIELDS) draft[field] = ""
  return { ...draft, ...overrides }
}

describe("buildManifestPatch", () => {
  test("omits fields unchanged from the original", () => {
    const original: Manifest = { name: "Book", description: "About" }
    const draft = draftOf({ name: "Book", description: "About" })
    expect(buildManifestPatch(original, draft)).toEqual({})
  })

  test("includes only fields whose value changed", () => {
    const original: Manifest = { name: "Book", version: "1.0.0" }
    const draft = draftOf({ name: "Better Book", version: "1.0.0" })
    expect(buildManifestPatch(original, draft)).toEqual({ name: "Better Book" })
  })

  test("treats an absent original field as an empty string (no spurious diff)", () => {
    // original has no `category`; draft leaves it blank -> nothing to send.
    const original: Manifest = { name: "Book" }
    const draft = draftOf({ name: "Book" })
    expect(buildManifestPatch(original, draft)).toEqual({})
  })

  test("sends an empty string when the user clears a previously-set field", () => {
    const original: Manifest = { name: "Book", description: "About" }
    const draft = draftOf({ name: "Book", description: "" })
    expect(buildManifestPatch(original, draft)).toEqual({ description: "" })
  })

  test("coerces non-string original values before comparing", () => {
    // A manifest value can be any JSON type; `written_date` here is a number.
    const original: Manifest = { written_date: 2026 as unknown as string }
    const draft = draftOf({ written_date: "2026" })
    expect(buildManifestPatch(original, draft)).toEqual({})
  })
})

// ── pickerOptions ────────────────────────────────────────────────────────────

describe("pickerOptions", () => {
  test("returns an empty array for null sections", () => {
    expect(pickerOptions(null)).toEqual([])
  })

  test("flattens items followed by their indented children", () => {
    const sections: IndexSections = {
      levels: ["book", "chapter"],
      items: [
        {
          title: "Genesis",
          ref: "Genesis",
          children: [
            { title: "1", ref: "Genesis 1" },
            { title: "2", ref: "Genesis 2" },
          ],
        },
        { title: "Exodus", ref: "Exodus", children: [] },
      ],
    }
    expect(pickerOptions(sections)).toEqual([
      { ref: "Genesis", label: "Genesis" },
      { ref: "Genesis 1", label: "  1" },
      { ref: "Genesis 2", label: "  2" },
      { ref: "Exodus", label: "Exodus" },
    ])
  })

  test("handles a single-level corpus (items with no children)", () => {
    const sections: IndexSections = {
      levels: ["book"],
      items: [{ title: "mini", ref: "mini", children: [] }],
    }
    expect(pickerOptions(sections)).toEqual([{ ref: "mini", label: "mini" }])
  })
})

// ── manifestFieldLabel ───────────────────────────────────────────────────────

describe("manifestFieldLabel", () => {
  test("returns a non-empty label for every editable field", () => {
    for (const field of EDITABLE_MANIFEST_FIELDS) {
      expect(manifestFieldLabel(field).length).toBeGreaterThan(0)
    }
  })

  test("gives distinct labels to distinct fields", () => {
    const labels = EDITABLE_MANIFEST_FIELDS.map(manifestFieldLabel)
    expect(new Set(labels).size).toBe(EDITABLE_MANIFEST_FIELDS.length)
  })
})
