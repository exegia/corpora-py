import type { UIMessage } from "ai"
import { corpusDisplayName, type LoadedCorpus } from "./corpus-load"

/**
 * Builds the seeded first assistant message — a friendly, conversational
 * introduction to the corpus that was just loaded ("This is **X** … it holds
 * **N words** across …") — and the corpus-specific suggestion chips shown
 * under it. Both are derived locally from the fetched manifest + index — no
 * model call — so they render the instant loading finishes; the message is
 * part of the `useChat` history, so the model also sees it as its own prior
 * turn.
 */

const formatCount = (count: number): string => count.toLocaleString("en-US")

const article = (word: string): string =>
  /^[aeiou]/i.test(word) ? "an" : "a"

/** Naive pluralizer for node-type names ("page" → "pages", "corpus" → "corpus"). */
const plural = (word: string, count: number): string =>
  count === 1 || /s$/i.test(word) ? word : `${word}s`

/** "a, b and c" */
const joinAnd = (parts: string[]): string =>
  parts.length <= 1
    ? (parts[0] ?? "")
    : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`

/** End a fragment with exactly one closing period. */
const sentence = (text: string): string =>
  /[.!?…]$/.test(text) ? text : `${text}.`

/** Trim an ISO timestamp down to its date; pass anything else through. */
const friendlyDate = (value: string | undefined): string | undefined => {
  const trimmed = value?.trim()
  if (!trimmed) return undefined
  const isoMatch = /^(\d{4}-\d{2}-\d{2})T/.exec(trimmed)
  return isoMatch ? isoMatch[1] : trimmed
}

export const welcomeText = (corpus: LoadedCorpus): string => {
  const { manifest, index } = corpus
  const name = corpusDisplayName(corpus)
  const sentences: string[] = []

  // "This is **X** — a commentary in Greek, written 318."
  const kind = (manifest.category || manifest.type || "corpus")
    .trim()
    .toLowerCase()
  const flavor: string[] = []
  if (manifest.language) flavor.push(`in ${manifest.language}`)
  const written = friendlyDate(manifest.written_date)
  if (written) flavor.push(`written ${written}`)
  sentences.push(
    `This is **${name}** — ${article(kind)} ${kind}` +
      (flavor.length > 0 ? ` ${flavor.join(", ")}` : "") +
      `, loaded and ready to explore.`
  )

  if (manifest.description?.trim()) {
    sentences.push(sentence(manifest.description.trim()))
  }

  // "It holds **38,548 words** across 134 pages and 1 book." — the
  // biggest-count node type reads as the corpus's atomic unit ("words"),
  // everything else as the containers they sit in.
  const types = [...index.node_types].sort((a, b) => b.count - a.count)
  if (types.length > 0) {
    const [atoms, ...containers] = types
    const across = containers.map(
      (nt) => `${formatCount(nt.count)} ${plural(nt.type, nt.count)}`
    )
    sentences.push(
      `It holds **${formatCount(atoms.count)} ${plural(atoms.type, atoms.count)}**` +
        (across.length > 0 ? ` across ${joinAnd(across)}` : "") +
        `.`
    )
  }

  // "The text is organized by book, opening at “Genesis”."
  const sections = index.sections
  if (sections && sections.items.length > 0) {
    const levels = sections.levels.join(" › ")
    const first = sections.items[0]?.title
    sentences.push(
      `The text is organized by ${levels || "section"}` +
        (first ? `, opening at “${first}”` : "") +
        `.`
    )
  }

  sentences.push(
    "Ask me anything about it — I can read passages, explain how the text " +
      "is structured, and inspect the graph nodes behind it. The " +
      "suggestions below are a good place to start."
  )
  return sentences.join(" ")
}

/** The seeded first assistant message shown when the chat opens. */
export const welcomeMessage = (corpus: LoadedCorpus): UIMessage => ({
  id: `welcome-${corpus.filename}`,
  role: "assistant",
  parts: [{ type: "text", text: welcomeText(corpus) }],
})

/** A few prompts tailored to the loaded corpus's actual contents. */
export const suggestionsFor = (corpus: LoadedCorpus): string[] => {
  const name = corpusDisplayName(corpus)
  const items = corpus.index.sections?.items ?? []
  const suggestions: string[] = [`What is “${name}” about?`]
  if (items[0]) suggestions.push(`Summarize “${items[0].title}”`)
  if (items[1])
    suggestions.push(`What are the key themes of “${items[1].title}”?`)
  suggestions.push("How is the text structured?")
  return suggestions
}
