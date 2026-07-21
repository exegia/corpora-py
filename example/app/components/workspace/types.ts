/**
 * UI-only chat types shaped after the Vercel AI SDK UI (`UIMessage`) contract:
 * a message is `{ id, role, parts }` where custom structured data travels as
 * `data-*` parts. Keeping the same shape means a real `useChat` +
 * `DefaultChatTransport` can replace `useMockChat` later without touching the
 * rendering layer.
 */

/** A structured pointer from the chat back to a corpus passage. */
export type CorpusReference = {
  /** Stable id for list rendering / removal. */
  id: string
  /** Route `:id` of the corpus the passage belongs to. */
  corpusId: string
  /** Backend passage ref (e.g. "GEN 1:1"). */
  ref: string
  /** Registry key of the exact rendered block (`${ref}#${index}`). */
  blockKey: string
  /** Short excerpt shown in tooltips / previews. */
  excerpt: string
  /** Graph node id of the passage, when the backend provided one — the handle
   * the AI agent uses to inspect/annotate the node over MCP. */
  node?: number
}

export type TextPart = { type: "text"; text: string }

export type CorpusReferencePart = {
  type: "data-corpusReference"
  data: CorpusReference
}

/** One agent tool invocation, rendered as an activity row in the message. */
export type ToolActivityPart = {
  type: "tool"
  toolCallId: string
  name: string
  state: "running" | "done" | "error"
  /** Short human-readable summary of the call (e.g. "node 38552"). */
  detail?: string
}

export type MessagePart = TextPart | CorpusReferencePart | ToolActivityPart

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  parts: MessagePart[]
}

/** Mirrors the AI SDK's `useChat` status values (minus "error"). */
export type ChatStatus = "ready" | "submitted" | "streaming"

/** Small id helper — `crypto.randomUUID` with a fallback for older webviews. */
export const makeId = (): string =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2)
