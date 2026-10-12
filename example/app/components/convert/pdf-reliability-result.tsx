import { useState } from "react"
import { Badge } from "~/components/ui/badge"
import type { SourceReliability } from "~/lib/atoms/upload-atom"

const verdicts = {
  loss: "Loss — try another format",
  review: "Passed — review and edit required",
  pass: "Passed",
  unscored: "Unscored — acceptance held",
}

export function PdfReliabilityResult({
  report,
}: {
  report: SourceReliability
}) {
  const [visibleMismatches, setVisibleMismatches] = useState(50)
  const automatic = report.assessment_kind === "automatic-ocr-agreement"
  const score = report.score_percent
  const rounded = score === null ? null : Number(score.toFixed(1))
  const displayScore =
    score !== null &&
    ((score < 50 && rounded === 50) || (score > 90 && rounded === 90))
      ? String(score)
      : score?.toFixed(1)
  return (
    <section
      aria-label="PDF source reliability"
      className="rounded-xl border border-border bg-background p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">Source reliability</h3>
        <Badge variant={report.passed ? "secondary" : "destructive"}>
          {score === null ? "Unscored" : `${displayScore}%`}
        </Badge>
      </div>
      <p className="mt-2 text-sm font-medium">{verdicts[report.decision]}</p>
      <p className="mt-1 text-sm text-muted-foreground">{report.message}</p>
      {automatic && (
        <p className="mt-2 text-sm text-muted-foreground">
          Automatic visual comparison · {report.comparison_engine} · {report.compared_pages} pages.
          This score estimates OCR agreement; both engines can make mistakes.
        </p>
      )}
      {report.dimension_scores && (
        <div className="mt-3 text-sm">
          <p className="text-muted-foreground">
            The final score uses the lowest measured agreement for all text and scripts present in the independent reference.
          </p>
          <dl className="mt-2 flex flex-wrap gap-4">
            {Object.entries(report.dimension_scores).map(([dimension, value]) => (
              <div key={dimension}>
                <dt className="capitalize text-muted-foreground">{dimension === "text" ? "All text" : dimension}</dt>
                <dd className="font-medium">{value.toFixed(1)}%</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {report.bundle && (
        <p className="mt-3 text-sm text-muted-foreground">
          The C-USX archive includes this score and all {report.mismatches.length} mismatches
          {report.bundle.independent_snapshot ? ", plus the independent OCR snapshot and runtime lock." : "."}
        </p>
      )}
      {report.decision === "unscored" && (
        <p className="mt-2 text-sm text-muted-foreground">
          Forced OCR completed. An independent comparison with the visible PDF
          pages is still needed before this result can be accepted.
        </p>
      )}
      {report.mismatches.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer font-medium">
            Review {report.mismatches.length} mismatches
          </summary>
          <div className="mt-2 max-h-80 space-y-3 overflow-auto">
            {report.mismatches.slice(0, visibleMismatches).map((mismatch, index) => (
              <div key={index} className="rounded-lg border border-border p-3">
                <p className="font-medium">Page {mismatch.page_number}</p>
                <p className="mt-1 text-xs text-muted-foreground">{automatic ? "Independent visual OCR" : "Expected"}</p>
                <pre
                  dir="auto"
                  className="text-xs break-words whitespace-pre-wrap"
                >
                  {mismatch.expected || "(empty)"}
                </pre>
                <p className="mt-2 text-xs text-muted-foreground">Converted</p>
                <pre
                  dir="auto"
                  className="text-xs break-words whitespace-pre-wrap"
                >
                  {mismatch.actual || "(empty)"}
                </pre>
              </div>
            ))}
          </div>
          {visibleMismatches < report.mismatches.length && (
            <button type="button" className="mt-2 underline" onClick={() => setVisibleMismatches((count) => count + 50)}>
              Show 50 more mismatches ({Math.min(visibleMismatches, report.mismatches.length)} of {report.mismatches.length} shown)
            </button>
          )}
        </details>
      )}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer font-medium">
          Conversion snapshot and hashes
        </summary>
        <dl className="mt-2 space-y-2 text-xs">
          {[
            [
              "Converter",
              report.converter_version
                ? `Docling ${report.converter_version} · forced PDF OCR`
                : report.converter,
            ],
            ["Original PDF SHA-256", report.source_sha256],
            ["OCR snapshot SHA-256", report.snapshot_sha256],
            ["Runtime lock SHA-256", report.lock_sha256],
            ["Comparison snapshot SHA-256", report.comparison_snapshot_sha256],
            ["Comparison lock SHA-256", report.comparison_lock_sha256],
            ["Bundled reliability report", report.bundle?.report],
            ["Bundled independent OCR", report.bundle?.independent_snapshot],
          ]
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <div key={label}>
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="mt-1 font-mono break-all">{value}</dd>
              </div>
            ))}
        </dl>
      </details>
    </section>
  )
}
