/**
 * Premade curation prompts for the chat composer — one per known defect
 * family in converter output. Clicking a chip fills the composer (it never
 * auto-sends), so the user can attach the relevant blocks first and edit the
 * wording. The agent's system prompt (`use-corpus-chat.ts`) documents the
 * matching annotation conventions (`section:` / `text fix:` note prefixes).
 */

export type PremadePrompt = {
  id: string
  /** Short chip label. */
  label: string
  /** Tooltip / accessible description of what the prompt does. */
  description: string
  /** The composer text inserted on click. */
  prompt: string
}

export const PREMADE_PROMPTS: PremadePrompt[] = [
  {
    id: "fix-sections",
    label: "Fix sections",
    description:
      "Audit the section structure: group blocks under their real headings",
    prompt:
      "Audit the section structure of this corpus. The converter often gets " +
      "sections wrong: a real section (e.g. a chapter) should span every " +
      "block from one heading (an 'Introduction', a chapter title, …) until " +
      "the next heading, but converted output may type each page or " +
      "paragraph as its own section, or not mark headings at all. Use " +
      "corpus_index to see the current section levels and counts, read the " +
      "attached passages (or page through corpus_content) to find the real " +
      "heading boundaries, and inspect boundary nodes with corpus_node_get. " +
      "For each node whose type or grouping is wrong, record a correction " +
      "with corpus_node_annotate — corrected otype if mistyped, and a " +
      "`section: …` note naming the section it starts or belongs to (e.g. " +
      "\"section: begins 'Introduction', spans until the next heading " +
      'node"). Finish with the corrected section map you propose.',
  },
  {
    id: "fix-text",
    label: "Fix text",
    description:
      "Audit text rendition: clean up malformed-PDF artifacts in passages",
    prompt:
      "Audit the text rendition of the attached passages (or the first " +
      "pages if none are attached). This corpus was converted from a " +
      "malformed PDF, so passage text can carry broken line-wraps, " +
      "mid-word hyphenation, ligature or encoding junk, repeated " +
      "headers/footers, and OCR noise. Inspect each affected node with " +
      "corpus_node_get, decide what the text should read as, and record it " +
      "with corpus_node_annotate using a `text fix: …` note containing the " +
      "cleaned-up text. Only change otype if it is also wrong. Summarize " +
      "every fix you record, per node.",
  },
  {
    id: "fix-clause",
    label: "Fix clause",
    description:
      "Audit clause-level typing: clause vs sentence vs paragraph spans",
    prompt:
      "Audit clause-level node typing for the attached passages (or a " +
      "sample from the corpus). Check the graph model facts with " +
      "corpus_node_get: a clause-sized span mistyped as a sentence, " +
      "paragraph, or page — or a node typed 'clause' that actually spans " +
      "several clauses or a single word — is a conversion error. Judge each " +
      "node by its slot span, features, and text, and record corrections " +
      "with corpus_node_annotate (corrected otype plus a one-line note " +
      "explaining the boundary you determined). Report each node's " +
      "converted type, your verdict, and what you recorded.",
  },
]
