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
| `processing` | `uploading` / `queued` / `converting` | `FileSummary`                        | `ProcessingStages` + logs   |
| `completed`  | `ready` / `success`                   | `FileSummary` + `CompletedResult`    | stages (all done) + logs    |
| `failed`     | `error`                               | `FileSummary` + `FailedResult`       | stages (failure marked) + logs |

## Pipeline stages (`deriveStages`)

Each stage maps to a real observable event — nothing is simulated:

1. **File received** — a file passed the client-side extension check.
2. **File type validated** — `detectSourceFormat` resolved a `source_format`.
3. **Uploaded to conversion service** — the `POST /convert` round-trip.
4. **Queued for conversion** — server acknowledged the job (`queued`).
5. **Converting to .corpus** — server `running`; carries the server's coarse
   log checkpoints. Server log lines matching `/warn/i` put this stage in
   the `warning` state without interrupting the run.
6. **Archive downloaded** — the `.corpus` blob fetched into memory (`ready`).

Stage states: `pending → active → completed | warning | failed`. Completed
stages stay visible. A failure marks the stage it happened in (`upload` when
the POST never got a job id, `converting` otherwise) and later stages stay
`pending`.

## Motion

Animation is used only for state changes: a fade/slide when a panel appears,
a fade on new log lines, and a spinner on the active stage. Everything is
gated with `motion-reduce:*` so reduced-motion preferences are respected.
