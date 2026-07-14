# Convert experience — state model

Components for the `/corpus/convert` upload-and-conversion flow. All state
lives in `uploadAtom` (`~/lib/atoms/upload-atom`) and is written only by the
module-level manager (`~/lib/uploads/manager`); everything in this directory
*derives* view state from it (`state-model.ts`) and renders.

## View states

```
                       ┌────────────────────────────────────────────┐
                       │                                            │ remove /
                       ▼                                            │ replace /
 ┌───────┐  valid   ┌────────────┐  server done   ┌───────────┐     │ convert
 │ empty │ ───────▶ │ processing │ ─────────────▶ │ completed │ ────┤ another
 └───────┘  file    └────────────┘  + downloaded  └───────────┘     │
   ▲  │                   │                                         │
   │  │ unsupported       │ any step errors       ┌───────────┐     │
   │  ▼ file              └─────────────────────▶ │  failed   │ ────┘
   │ (inline error,                               └───────────┘
   │  stays in empty)                                   │ retry
   └────────────────────────────────────────────────────┘ (re-runs upload)
```

| View         | `UploadEntry.status`                  | Left column                          | Right column (console)      |
|--------------|---------------------------------------|--------------------------------------|-----------------------------|
| `empty`      | *(no entry)*                          | `UploadDropzone` (+ inline rejection)| hidden                      |
| `processing` | `uploading` / `queued` / `converting` / `validating` | `FileSummary`         | `ProcessingStages` + logs   |
| `completed`  | `ready` / `success`                   | `FileSummary` + `CompletedResult`    | stages (all done) + logs    |
| `failed`     | `error`                               | `FileSummary` + `FailedResult`       | stages (failure marked) + logs |

## ZIP inspection

A `.zip` is a container, not a format. Before uploading one, the client
reads its central directory (`~/lib/uploads/inspect-zip.ts` -- entry names
only, no full read) and routes it:

- contains `.tf` files → a Text-Fabric dataset → uploaded as `tf_zip`
  (the pre-existing behavior);
- contains only TEI/XML documents (two or more) → a TEI corpus → uploaded as
  `tei_zip` (the server converts every member into one dataset);
- contains exactly one convertible document (`.tei`/`.xml`/`.epub`/`.html`/
  `.pdf`/`.txt`/…) → extracted in the browser (`DecompressionStream`) and
  continues the normal single-file flow;
- anything else (mixed documents, nothing convertible, empty) → rejected
  inline with an inventory of what was found -- the service has no converter
  for it, so it never leaves the machine;
- uninspectable (ZIP64/unusual layout) → falls back to `tf_zip` and lets the
  server validate, so inspection never breaks an upload that used to work.

The findings appear as log lines under the "File type validated" stage.

## Pipeline stages (`deriveStages`)

Each stage maps to a real observable event — nothing is simulated — and
carries its own log lines, rendered inline under the stage in the timeline.
The console's bottom block shows only the final success/error completion
message.

1. **File received** — a file passed the client-side extension check.
2. **File type validated** — `detectSourceFormat` resolved a `source_format`.
3. **Uploaded to conversion service** — the `POST /convert` round-trip.
4. **Queued for conversion** — server acknowledged the job (`queued`).
5. **Converting to .corpus** — server `running`; carries the server's coarse
   log checkpoints. Server log lines matching `/warn/i` put this stage in
   the `warning` state without interrupting the run.
6. **Dataset validated** — after the server reports `succeeded`, the client
   POSTs `/validate` with the job id (`admin.services.validation_api`) and the
   server runs the result archive through the full `.tf → .cfm → mmap` load
   cycle. `valid` → completed with corpus stats; `invalid` → the stage is
   marked failed and the reasons are logged, but the download/save flow is
   NOT blocked — the verdict annotates the conversion, it doesn't gate it. An
   unreachable `/validate` (network error) shows as a `warning` ("skipped"),
   as do history entries converted before this stage existed.
7. **Archive downloaded** — the `.corpus` blob fetched into memory (`ready`).

Stage states: `pending → active → completed | warning | failed`. Completed
stages stay visible. A failure marks the stage it happened in (`upload` when
the POST never got a job id, `converting` otherwise) and later stages stay
`pending`.

## Motion

Animation is used only for state changes: a fade/slide when a panel appears,
a fade on new log lines, and a spinner on the active stage. Everything is
gated with `motion-reduce:*` so reduced-motion preferences are respected.
