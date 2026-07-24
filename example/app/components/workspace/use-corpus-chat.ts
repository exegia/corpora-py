import { useCallback, useRef, useState } from "react"
import { ToolLoopAgent, isStepCount, type ModelMessage } from "ai"
import { createMCPClient, type MCPClient } from "@ai-sdk/mcp"
import { API_URL } from "~/lib/types/socket"
import { agentModelId, createAgentModel } from "~/lib/agent-model"
import { authHeaders, boundFetch, hasValidAnthropicKey, useApiKeys } from "~/lib/settings"

import { loadGraphModelDoc } from "./graph-model"
import {
  makeId,
  type ChatMessage,
  type ChatStatus,
  type CorpusReference,
  type MessagePart,
} from "./types"

/**
 * The workspace chat brain: a `ToolLoopAgent` running in the webview, loaded
 * with the Context-Fabric graph-model doc and the corpora-api MCP tools
 * (`corpus_*` — content, node inspect, node annotate), behind a
 * `useChat`-shaped surface (`messages`, `status`, `sendMessage`, `ownKey`).
 * Its job: audit whether converted nodes carry the right type (slot vs
 * non-slot, word vs clause vs paragraph, ...) and record corrections via
 * `corpus_node_annotate`.
 *
 * The model is picked per run by `createAgentModel` (see `~/lib/agent-model`):
 * the user's own Anthropic key when one is saved + validated in Settings,
 * otherwise the free demo model through this deployment's `/api/gateway`
 * proxy — the same two modes as the `/chat` route's `ChatView`.
 *
 * Conversation state is in-memory only; nothing is persisted.
 */

/** Tool-loop ceiling — inspect + annotate a handful of nodes, not run away. */
const MAX_STEPS = 12

const SEED_MESSAGES: ChatMessage[] = [
  {
    id: "seed-welcome",
    role: "assistant",
    parts: [
      {
        type: "text",
        text:
          "Hi — I'm the corpus assistant. Attach a passage and ask me to " +
          "check its node type (slot vs non-slot, word/clause/paragraph…): " +
          "I inspect the graph over MCP and record corrections. Add an " +
          "Anthropic API key in Settings to switch from the free demo " +
          "model to Claude.",
      },
    ],
  },
]

// ── Agent plumbing ──────────────────────────────────────────────────────────

const systemPrompt = (corpusFilename: string, graphModelDoc: string): string =>
  `You are the corpus curation assistant inside the Corpora desktop app.

The user is reading the stored corpus archive "${corpusFilename}" — a
Text-Fabric / Context-Fabric dataset produced by an automated converter. The
conversion may be imperfect: nodes can carry the wrong node type (otype) for
what their text actually is.

Your job, when the user attaches passages (each carries a graph node id):
1. Inspect each node with the corpus_node_get tool (filename
   "${corpusFilename}"). Look at its otype, is_slot, slot span, features, and
   text.
2. Judge whether the converted otype matches the graph model below and the
   node's actual content (e.g. a single token typed as "paragraph", a clause
   typed as "sentence", a non-slot type used for atomic text).
3. If the type is wrong, record the correction with corpus_node_annotate
   (corrected otype + a one-sentence note). If it is correct, say so — do not
   annotate nodes that are fine.
4. Use corpus_content / corpus_index for surrounding context when needed.
5. Report plainly: per node, the converted type, your verdict, and what you
   recorded. Refer to nodes as "node <id>".

Only the node types listed by corpus_node_get's node_types (or a clearly
justified new type from the graph model's vocabulary) are acceptable otype
values. Never invent tool arguments; never annotate without inspecting first.

Common curation tasks (the composer offers premade prompts for these):
- **Fix sections** — converter output often mis-scopes sections: a real
  section (e.g. a chapter) spans every block from one heading (an
  "Introduction", a chapter title, …) until the next heading, but the
  converter may type each page/paragraph as its own section or leave headings
  unmarked. Map the true boundaries from the text, then annotate boundary
  nodes: corrected otype when mistyped, plus a note prefixed "section: "
  describing the grouping (e.g. "section: begins 'Introduction'").
- **Fix text** — corpora converted from malformed PDFs carry broken
  line-wraps, mid-word hyphenation, ligature/encoding junk, repeated
  headers/footers, OCR noise. Record the cleaned-up reading in a note
  prefixed "text fix: " (the sidecar is the fix's home — passage text itself
  is never rewritten). Leave otype alone unless it is also wrong.
- **Fix clause** (and similar type-level audits) — verify clause/sentence/
  paragraph-sized spans carry the right otype for their slot span and
  content; annotate with the corrected otype and a one-line boundary note.

The "section: " / "text fix: " note prefixes are conventions downstream
tooling parses — keep them exact.

# Context-Fabric graph model (reference)

${graphModelDoc}`

/** User-turn text sent to the model: the typed text plus structured refs. */
const modelUserText = (
  text: string,
  references: CorpusReference[],
  corpusFilename: string
): string => {
  const refLines = references.map(
    (r) =>
      `<attached-passage corpus="${corpusFilename}"` +
      (r.node != null ? ` node="${r.node}"` : "") +
      ` ref="${r.ref}">${r.excerpt}</attached-passage>`
  )
  return [text.trim(), ...refLines].filter(Boolean).join("\n\n")
}

/** Compact one-line summary of a tool call's input for the activity row. */
const toolDetail = (input: unknown): string | undefined => {
  if (input == null || typeof input !== "object") return undefined
  const record = input as Record<string, unknown>
  const bits: string[] = []
  if (typeof record.node === "number") bits.push(`node ${record.node}`)
  if (typeof record.otype === "string") bits.push(`→ ${record.otype}`)
  if (typeof record.ref === "string" && record.ref)
    bits.push(String(record.ref))
  return bits.length ? bits.join(" ") : undefined
}

export type SendMessageInput = {
  text: string
  references?: CorpusReference[]
}

export function useCorpusChat(corpusId: string) {
  const keys = useApiKeys()
  const ownKey = hasValidAnthropicKey(keys)
  const [messages, setMessages] = useState<ChatMessage[]>(SEED_MESSAGES)
  const [status, setStatus] = useState<ChatStatus>("ready")
  // Model-side conversation history — parallel to the UI list.
  const modelMessagesRef = useRef<ModelMessage[]>([])
  const corpusFilename = `${corpusId}.corpus`

  const appendUserMessage = useCallback(
    (text: string, references: CorpusReference[]) => {
      const parts: MessagePart[] = [
        ...(text.trim().length > 0
          ? [{ type: "text", text: text.trim() } as MessagePart]
          : []),
        ...references.map((reference): MessagePart => ({
          type: "data-corpusReference",
          data: reference,
        })),
      ]
      if (parts.length === 0) return false
      setMessages((prev) => [...prev, { id: makeId(), role: "user", parts }])
      return true
    },
    []
  )

  const sendLive = useCallback(
    async (text: string, references: CorpusReference[]) => {
      const assistantId = makeId()
      // Mutated in place while streaming, then committed via setMessages —
      // React state stays the single source of truth for rendering.
      let parts: MessagePart[] = []
      const commit = () => {
        const snapshot = [...parts]
        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantId
              ? { ...message, parts: snapshot }
              : message
          )
        )
      }

      let mcpClient: MCPClient | undefined
      try {
        const graphModelDoc = await loadGraphModelDoc()

        mcpClient = await createMCPClient({
          transport: {
            type: "http",
            url: `${API_URL}/mcp/`,
            headers: authHeaders(),
            fetch: boundFetch,
          },
        })
        const allTools = await mcpClient.tools()
        // Only the stored-archive tools: the runtime search tools operate on
        // CLI-loaded datasets, not the Hub archives this app displays.
        const tools = Object.fromEntries(
          Object.entries(allTools).filter(([name]) =>
            name.startsWith("corpus_")
          )
        )

        const agent = new ToolLoopAgent({
          model: createAgentModel(ownKey),
          instructions: systemPrompt(corpusFilename, graphModelDoc),
          tools,
          stopWhen: isStepCount(MAX_STEPS),
        })

        modelMessagesRef.current.push({
          role: "user",
          content: modelUserText(text, references, corpusFilename),
        })

        setMessages((prev) => [
          ...prev,
          { id: assistantId, role: "assistant", parts: [] },
        ])

        const result = await agent.stream({
          messages: modelMessagesRef.current,
        })

        for await (const part of result.fullStream) {
          switch (part.type) {
            case "text-delta": {
              setStatus("streaming")
              const last = parts[parts.length - 1]
              if (last?.type === "text") last.text += part.text
              else parts.push({ type: "text", text: part.text })
              commit()
              break
            }
            case "tool-call": {
              setStatus("streaming")
              parts.push({
                type: "tool",
                toolCallId: part.toolCallId,
                name: part.toolName,
                state: "running",
                detail: toolDetail(part.input),
              })
              commit()
              break
            }
            case "tool-result":
            case "tool-error": {
              const ok = part.type === "tool-result"
              parts = parts.map((p) =>
                p.type === "tool" && p.toolCallId === part.toolCallId
                  ? { ...p, state: ok ? "done" : "error" }
                  : p
              )
              commit()
              break
            }
            case "error":
              throw part.error instanceof Error
                ? part.error
                : new Error(String(part.error))
            default:
              break
          }
        }

        // Echo the discussed references as chips + record the turn for the
        // next model call.
        for (const reference of references) {
          parts.push({ type: "data-corpusReference", data: reference })
        }
        commit()
        modelMessagesRef.current.push({
          role: "assistant",
          content: await result.text,
        })
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        parts = parts.map((p) =>
          p.type === "tool" && p.state === "running"
            ? { ...p, state: "error" as const }
            : p
        )
        parts.push({
          type: "text",
          text: `⚠️ The agent run failed: ${message}`,
        })
        setMessages((prev) =>
          prev.some((m) => m.id === assistantId)
            ? prev.map((m) =>
                m.id === assistantId ? { ...m, parts: [...parts] } : m
              )
            : [...prev, { id: assistantId, role: "assistant", parts }]
        )
        // Drop the failed turn so a retry re-sends it cleanly.
        if (modelMessagesRef.current.at(-1)?.role === "user") {
          modelMessagesRef.current.pop()
        }
      } finally {
        void mcpClient?.close().catch(() => {})
        setStatus("ready")
      }
    },
    [corpusFilename, ownKey]
  )

  // ── Public surface ────────────────────────────────────────────────────────

  const sendMessage = useCallback(
    ({ text, references = [] }: SendMessageInput) => {
      if (!appendUserMessage(text, references)) return
      setStatus("submitted")
      void sendLive(text, references)
    },
    [appendUserMessage, sendLive]
  )

  return { messages, status, sendMessage, ownKey, model: agentModelId(ownKey) }
}
