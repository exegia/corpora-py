import { expect, test } from "bun:test"
import { renderToStaticMarkup } from "react-dom/server"
import type { SourceReliability } from "~/lib/atoms/upload-atom"
import { PdfReliabilityResult } from "./pdf-reliability-result"

const base: SourceReliability = {
  score_percent: null,
  decision: "unscored",
  passed: false,
  review_required: true,
  message: "Independent comparison required",
  mismatches: [],
  converter_version: "2.137.0",
  source_sha256: "sha256:source",
  snapshot_sha256: "sha256:snapshot",
}

test("unscored OCR explains the acceptance hold and preserves source identity", () => {
  const html = renderToStaticMarkup(<PdfReliabilityResult report={base} />)
  expect(html).toContain("Unscored — acceptance held")
  expect(html).toContain("Docling 2.137.0")
  expect(html).toContain("sha256:snapshot")
  expect(html).toContain("visible PDF pages")
})

test("review passes expose literal Hebrew mismatches without interpreting markup", () => {
  const html = renderToStaticMarkup(
    <PdfReliabilityResult
      report={{
        ...base,
        score_percent: 75,
        decision: "review",
        passed: true,
        mismatches: [
          {
            page_number: 2,
            expected: "שָׁלוֹם",
            actual: "<script>שלום</script>",
          },
        ],
      }}
    />
  )
  expect(html).toContain("Passed — review and edit required")
  expect(html).toContain("Page 2")
  expect(html).toContain("שָׁלוֹם")
  expect(html).toContain("&lt;script&gt;")
})

test("score display preserves acceptance boundaries", () => {
  for (const score of [49.9999, 90.0001]) {
    const html = renderToStaticMarkup(
      <PdfReliabilityResult report={{ ...base, score_percent: score }} />
    )
    expect(html).toContain(`${score}%`)
  }
})

test("automatic comparison identifies the independent evidence and its limits", () => {
  const html = renderToStaticMarkup(
    <PdfReliabilityResult report={{
      ...base,
      score_percent: 85,
      decision: "review",
      passed: true,
      assessment_kind: "automatic-ocr-agreement",
      comparison_engine: "Surya OCR 2 (0.22.1)",
      compared_pages: 21,
      comparison_snapshot_sha256: "sha256:independent-snapshot",
      dimension_scores: { text: 95.3, hebrew: 85 },
      mismatches: [{ page_number: 3, expected: "Visual text", actual: "Converted text" }],
    }} />
  )
  expect(html).toContain("85.0%")
  expect(html).toContain("Surya OCR 2 (0.22.1)")
  expect(html).toContain("21 pages")
  expect(html).toContain("both engines can make mistakes")
  expect(html).toContain("Independent visual OCR")
  expect(html).toContain("sha256:independent-snapshot")
  expect(html).toContain("lowest measured agreement")
  expect(html).toContain("All text")
  expect(html).toContain("95.3%")
})

test("bundled review evidence is identified on the export result", () => {
  const html = renderToStaticMarkup(<PdfReliabilityResult report={{
    ...base, score_percent: 99.36, decision: "pass", passed: true,
    bundle: {
      profile: "corpora-pdf-review/1",
      report: "assets/pdf/review/reliability.json",
      independent_snapshot: "assets/pdf/review/independent-ocr.json",
    },
    mismatches: [{ page_number: 1, expected: "I", actual: "Ι" }],
  }} />)
  expect(html).toContain("The C-USX archive includes this score and all 1 mismatches")
  expect(html).toContain("independent OCR snapshot and runtime lock")
  expect(html).toContain("assets/pdf/review/reliability.json")
})
