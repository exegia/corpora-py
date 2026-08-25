# CLAUDE.md — `admin.converters`

`Document`/`Unit` tree → Text-Fabric dataset → `.cfm` cache → `.corpus` archive. See
`packages/admin/CLAUDE.md` for the shared-schema/shared-walker architecture that makes this package
possible; this file covers the Text-Fabric, Context-Fabric, and `.corpus` details specific to
`converters/`.

Read `_walker.py` before touching any feature/node-creation logic — it's the one TF walk reused by
every `_{format}_to_tf.py`.

## Text-Fabric walker gotchas (all handled in `_walker.py`)

- **Every feature name must have metadata**, or `cv.walk()` fails validation with `"node feature has no metadata"`.
  Feature names here vary per document (HTML attributes, TEI `@type`, ...) so they can't be declared upfront in
  `featureMeta=`; `set_features()` registers each one dynamically via `cv.meta(name, valueType="str")` right before
  setting it. If you add a
  `cv.feature()` call anywhere, route it through `set_features()`, not
  `cv.feature()` directly, or you'll reintroduce this failure.
- **Dynamically-registered features need an explicit `valueType`** or the exporter warns `"Missing @valueType"`
  (non-fatal, but avoidable — that's why `set_features()` always passes `valueType="str"`).
- **A node covering zero slots gets silently deleted** by Text-Fabric's
  "remove unlinked nodes" pass. A leaf `Unit` with no tokens and no children (a blank PDF page, an `<img>`, an `<hr>`)
  would otherwise vanish along with its attributes — `_walk_unit()` gives genuinely empty leaves one placeholder
  empty-text slot so they survive.
- **`otext.sectionTypes`/`sectionFeatures` can't be empty.** The default is a single section level (the root
  `book`/`document`/`text` node, with `title` as its section feature), but a converter can declare finer levels by
  passing a `SectionSpec` to `convert_documents()` (issue #174) — `_category.categorize()` derives one
  (`book`/`chapter`/`verse`) from the roles actually present in the parsed tree, because **a declared section level
  with zero nodes breaks the TF walk**. The walker guarantees every node of a declared section type carries its label
  feature (`_section_label`: unit label → source id → per-parent 1-based ordinal), since a section node without one
  breaks `T.sectionFromNode`. Structure not declared as a section stays ordinary node types via `otype_for`.
- **Category classification (issue #176)**: `_category.categorize(documents, requested, ...)` detects
  `document`/`book`/`religious` from section roles (`verse`/`chapter`/`book` unit types, TEI `div@type`, level-1
  markdown sections), honors a downgrade override, downgrades an unexpressible upgrade with a warning, and returns the
  `SectionSpec` + `otype_for` wrapper to match. Converters return `ConvertedDataset` (a `Path` subclass) whose
  `.category` lands in `manifest.category` and `.warnings` on the job log.
- **`SKIP_TAGS` in `parsers/_html.py` is scoped to tags that only make sense to drop when nested inside `<body>`**
  (script/style/noscript/svg/math). It used to include `"head"` for HTML's metadata tag, which silently ate TEI's
  `<head>` (a heading element, reused by the shared walker) — don't add HTML-specific tag names back to that set without
  checking what they mean in TEI/XML first.

## Context-Fabric (`cfabric`) notes

- There is **no separate compile API**. `.cfm` compilation happens automatically the first time a dataset is loaded via
  `cfabric.Fabric(locations=...).loadAll()`. `convert_to_cfm()` exists only to trigger that load on purpose and hand
  back the resulting `.cfm` path.
- `Fabric(...).loadAll()` returns `Api | bool` (`False` on failure) — always narrow with `isinstance(result, bool)`
  before touching `.F`/`.T`/`.Fall()`; those are dynamically populated at load time so mypy can't see their attributes
  either (hence the `type: ignore[attr-defined]` in
  `convert_to_corpus.py`).

## `.corpus` archive

The archive format (`manifest.yml`, `toc.yml`, `assets/`, `.git/`,
`corpora/{*.tf, .cfm/}`) is the contract both the Corpora and Exegia apps parse. The canonical spec is maintained in an
external vault by the Corpora team. Before changing manifest/toc shape in `convert_to_corpus.py`, consult the current
schema definition with the team or check the app's schema loader to understand the expected format.

`convert_to_corpus` validates the archive it just wrote against the required top-level layout
(`manifest.yml`, `toc.yml`, `corpora/`) and raises `CorpusArchiveError` if any member is missing (issue #108). A
converter that returns a malformed zip can never reach a client's library: the error surfaces in the job's `error`
field as `"Conversion failed: CorpusArchiveError (job id X)"`, the job ends `FAILED`, and `/convert/{id}/download`
returns 409 (not the broken archive). `assets/` and `.git/` are deliberately not in the required set -- assets is
empty when the source has no cover/thumbnail, and `.git/` is skipped on runtimes without a `git` binary (see
`_git_snapshot`).

## Known gaps (converter-side)

Service-side gaps (progress reporting, job registry, archive cleanup) live in
`src/admin/services/CLAUDE.md`.

- **`_xml_to_tf.py` maps every XML element to a generic ``element`` otype** (mirroring the HTML converter, since
  `XmlParser` already reuses `element_to_unit` from `_html.py`). Generic XML has no fixed node-type vocabulary unlike
  TEI's `<div>`/`<p>` convention, so a single ``element`` otype is the correct mapping.
- `dataset_id`/`project_id`/`publisher_id`/`author_ids` in
  `convert_to_corpus()` are caller-supplied and default to `""` — this package has no way to know them; they're assigned
  by whatever backend calls it (the Corpora/Exegia app, not this converter).
