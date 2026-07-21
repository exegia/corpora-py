import { useCallback, useEffect, useRef, useState } from "react"

import {
  makeId,
  type ChatMessage,
  type ChatStatus,
  type CorpusReference,
  type MessagePart,
} from "./types"

/**
 * Mock stand-in for the AI SDK's `useChat` — same observable surface
 * (`messages`, `status`, `sendMessage`) and the same `UIMessage`-style parts
 * array, but replies come from a canned generator streamed word-by-word with
 * timers. No network, no persistence. Swap for `useChat` +
 * `DefaultChatTransport` when a backend exists.
 */

const SEED_MESSAGES: ChatMessage[] = [
  {
    id: "seed-welcome",
    role: "assistant",
    parts: [
      {
        type: "text",
        text:
          "Hi — I'm a mock corpus assistant (no model is connected). " +
          "Hover a passage on the left to copy it, quote it into this " +
          "composer, or attach it as a reference, then send me a question.",
      },
    ],
  },
]

/** Delay before the mock assistant "starts responding". */
const THINK_MS = 500
/** Interval between streamed words. */
const STREAM_MS = 35

const mockReply = (text: string, references: CorpusReference[]): string => {
  if (references.length > 0) {
    const refs = references.map((r) => r.ref).join(", ")
    const plural = references.length > 1 ? "passages" : "passage"
    return (
      `Here's a mock answer about ${refs}. In a real deployment I'd ground ` +
      `a streamed response in the attached ${plural}. Click a reference ` +
      `chip below to jump back to the original block in the reader.`
    )
  }
  if (text.trim().length > 0) {
    return (
      "This is a mock response — nothing was sent to a model. Try attaching " +
      "a passage as a structured reference and I'll echo it back as a " +
      "clickable citation."
    )
  }
  return "Send some text or attach a passage reference to see a mock reply."
}

export type SendMessageInput = {
  text: string
  references?: CorpusReference[]
}

export function useMockChat() {
  const [messages, setMessages] = useState<ChatMessage[]>(SEED_MESSAGES)
  const [status, setStatus] = useState<ChatStatus>("ready")
  const timersRef = useRef<number[]>([])

  // Clear any in-flight mock streaming on unmount.
  useEffect(
    () => () => {
      for (const timer of timersRef.current) {
        window.clearTimeout(timer)
        window.clearInterval(timer)
      }
    },
    []
  )

  const sendMessage = useCallback(
    ({ text, references = [] }: SendMessageInput) => {
      const userParts: MessagePart[] = [
        ...(text.trim().length > 0
          ? [{ type: "text", text: text.trim() } as MessagePart]
          : []),
        ...references.map((reference): MessagePart => ({
          type: "data-corpusReference",
          data: reference,
        })),
      ]
      if (userParts.length === 0) return

      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "user", parts: userParts },
      ])
      setStatus("submitted")

      const words = mockReply(text, references).split(" ")
      const assistantId = makeId()

      const thinkTimer = window.setTimeout(() => {
        setStatus("streaming")
        setMessages((prev) => [
          ...prev,
          { id: assistantId, role: "assistant", parts: [] },
        ])

        let revealed = 0
        const streamTimer = window.setInterval(() => {
          revealed += 1
          const done = revealed >= words.length
          const parts: MessagePart[] = [
            { type: "text", text: words.slice(0, revealed).join(" ") },
            // Citations arrive once the text finishes, like a real stream.
            ...(done
              ? references.map((reference): MessagePart => ({
                  type: "data-corpusReference",
                  data: reference,
                }))
              : []),
          ]
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId ? { ...message, parts } : message
            )
          )
          if (done) {
            window.clearInterval(streamTimer)
            setStatus("ready")
          }
        }, STREAM_MS)
        timersRef.current.push(streamTimer)
      }, THINK_MS)
      timersRef.current.push(thinkTimer)
    },
    []
  )

  return { messages, status, sendMessage }
}
