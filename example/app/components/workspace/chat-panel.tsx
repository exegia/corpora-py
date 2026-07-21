import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react"
import {
  BookOpen,
  Check,
  Loader2,
  PanelRightClose,
  SendHorizontal,
  Sparkles,
  Wrench,
  X,
} from "lucide-react"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import { Textarea } from "~/components/ui/textarea"
import { cn } from "~/lib/utils"

import type {
  ChatMessage,
  CorpusReference,
  CorpusReferencePart,
  ToolActivityPart,
} from "./types"
import { PREMADE_PROMPTS } from "./premade-prompts"
import { AGENT_MODEL, useCorpusChat } from "./use-corpus-chat"
import { useWorkspace } from "./workspace-context"

/**
 * The AI chat panel (right pane): header with collapse control, scrollable
 * message log, attachment chips, and a composer following the AI SDK UI
 * conventions (Enter sends, Shift+Enter breaks). The brain is
 * `useCorpusChat`: a real node-auditing agent when an Anthropic key is set in
 * Settings, a mock assistant otherwise.
 */
export function ChatPanel() {
  const {
    corpusId,
    attachments,
    removeAttachment,
    clearAttachments,
    focusBlock,
    pendingInsert,
    consumePendingInsert,
    setChatOpen,
    announce,
  } = useWorkspace()
  const { messages, status, sendMessage, live } = useCorpusChat(corpusId)
  const [input, setInput] = useState("")
  const logRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Keep the log pinned to the latest message while the mock reply streams.
  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [messages, status])

  // Consume "insert into composer" requests coming from corpus blocks.
  useEffect(() => {
    if (!pendingInsert) return
    setInput((prev) =>
      prev.trim() ? `${prev}\n\n${pendingInsert.text}` : pendingInsert.text
    )
    consumePendingInsert()
    textareaRef.current?.focus()
  }, [pendingInsert, consumePendingInsert])

  const canSend =
    status === "ready" && (input.trim().length > 0 || attachments.length > 0)

  const submit = () => {
    if (!canSend) return
    sendMessage({ text: input, references: attachments })
    setInput("")
    clearAttachments()
    announce("Message sent")
  }

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    submit()
  }

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const onReferenceClick = (reference: CorpusReference) => {
    focusBlock(reference.blockKey, reference.ref)
  }

  const insertPremadePrompt = (label: string, prompt: string) => {
    setInput((prev) => (prev.trim() ? `${prev}\n\n${prompt}` : prompt))
    textareaRef.current?.focus()
    announce(`Inserted "${label}" prompt into the composer`)
  }

  return (
    <section
      id="chat-panel"
      aria-label="AI chat panel"
      className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-card shadow-sm"
    >
      <header className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-amber-500" aria-hidden="true" />
          <h3 className="text-sm font-semibold">Assistant</h3>
          <Badge
            variant="secondary"
            title={
              live
                ? `Live agent (${AGENT_MODEL}) with corpus MCP tools`
                : "No Anthropic key set — add one in Settings for the live agent"
            }
          >
            {live ? AGENT_MODEL : "mock"}
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Collapse chat panel"
          aria-expanded="true"
          aria-controls="chat-panel"
          onClick={() => setChatOpen(false)}
          data-cuelume-press
          data-cuelume-release
        >
          <PanelRightClose className="size-4" aria-hidden="true" />
        </Button>
      </header>

      <div
        ref={logRef}
        role="log"
        aria-label="Chat messages"
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3"
      >
        {messages.map((message) => (
          <ChatMessageBubble
            key={message.id}
            message={message}
            onReferenceClick={onReferenceClick}
          />
        ))}

        {status !== "ready" && (
          <div
            role="status"
            className="flex items-center gap-2 text-xs text-muted-foreground"
          >
            <Loader2
              className="size-3 animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
            {status === "submitted" ? "Thinking…" : "Responding…"}
          </div>
        )}
      </div>

      <form
        onSubmit={onSubmit}
        className="flex shrink-0 flex-col gap-2 border-t p-3"
      >
        <ul aria-label="Premade prompts" className="flex flex-wrap gap-1.5">
          {PREMADE_PROMPTS.map((premade) => (
            <li key={premade.id}>
              <button
                type="button"
                title={premade.description}
                aria-label={`Insert premade prompt: ${premade.label} — ${premade.description}`}
                onClick={() =>
                  insertPremadePrompt(premade.label, premade.prompt)
                }
                data-cuelume-press
                data-cuelume-release
                className="inline-flex cursor-pointer items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-xs text-muted-foreground outline-none hover:border-amber-400 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60"
              >
                <Sparkles className="size-3" aria-hidden="true" />
                {premade.label}
              </button>
            </li>
          ))}
        </ul>

        {attachments.length > 0 && (
          <ul
            aria-label="Attached passage references"
            className="flex flex-wrap gap-1.5"
          >
            {attachments.map((attachment) => (
              <li
                key={attachment.id}
                className="inline-flex items-center gap-1 rounded-full border bg-muted py-0.5 pr-1 pl-2 text-xs"
                title={attachment.excerpt}
              >
                <BookOpen
                  className="size-3 text-muted-foreground"
                  aria-hidden="true"
                />
                <span className="max-w-40 truncate font-mono">
                  {attachment.ref}
                </span>
                <button
                  type="button"
                  aria-label={`Remove reference ${attachment.ref}`}
                  onClick={() => removeAttachment(attachment.id)}
                  className="cursor-pointer rounded-full p-0.5 outline-none hover:bg-background focus-visible:ring-2 focus-visible:ring-ring/60"
                >
                  <X className="size-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <label htmlFor="chat-composer" className="sr-only">
          Message the assistant
        </label>
        <Textarea
          id="chat-composer"
          ref={textareaRef}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onComposerKeyDown}
          placeholder="Ask about this corpus…"
          className="max-h-40 min-h-16 resize-none"
        />

        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] text-muted-foreground">
            Enter to send · Shift+Enter for a new line
          </p>
          <Button
            type="submit"
            size="sm"
            disabled={!canSend}
            className="gap-1.5"
            data-cuelume-press
            data-cuelume-release
          >
            <SendHorizontal className="size-4" aria-hidden="true" />
            Send
          </Button>
        </div>
      </form>
    </section>
  )
}

function ChatMessageBubble({
  message,
  onReferenceClick,
}: {
  message: ChatMessage
  onReferenceClick: (reference: CorpusReference) => void
}) {
  const isUser = message.role === "user"
  const text = message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n\n")
  const references = message.parts.filter(
    (part): part is CorpusReferencePart => part.type === "data-corpusReference"
  )
  const toolCalls = message.parts.filter(
    (part): part is ToolActivityPart => part.type === "tool"
  )

  if (!text && references.length === 0 && toolCalls.length === 0) return null

  return (
    <div
      className={cn(
        "flex max-w-[85%] flex-col gap-1.5",
        isUser ? "items-end self-end" : "items-start self-start"
      )}
    >
      {toolCalls.length > 0 && (
        <ul
          aria-label="Agent tool activity"
          className="flex flex-col gap-0.5 text-xs text-muted-foreground"
        >
          {toolCalls.map((tool) => (
            <li key={tool.toolCallId} className="flex items-center gap-1.5">
              {tool.state === "running" ? (
                <Loader2
                  className="size-3 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              ) : tool.state === "error" ? (
                <X className="size-3 text-destructive" aria-hidden="true" />
              ) : (
                <Check className="size-3 text-success" aria-hidden="true" />
              )}
              <Wrench className="size-3" aria-hidden="true" />
              <span className="font-mono">{tool.name}</span>
              {tool.detail && (
                <span className="truncate text-muted-foreground/70">
                  {tool.detail}
                </span>
              )}
              <span className="sr-only">
                {tool.state === "running"
                  ? "running"
                  : tool.state === "error"
                    ? "failed"
                    : "finished"}
              </span>
            </li>
          ))}
        </ul>
      )}
      {text && (
        <div
          className={cn(
            "rounded-xl px-3 py-2 text-sm whitespace-pre-wrap",
            isUser
              ? "rounded-br-sm bg-primary text-primary-foreground"
              : "rounded-bl-sm bg-muted text-foreground"
          )}
        >
          <span className="sr-only">
            {isUser ? "You said: " : "Assistant: "}
          </span>
          {text}
        </div>
      )}

      {references.length > 0 && (
        <div
          className="flex flex-wrap gap-1"
          aria-label={isUser ? "Referenced passages" : "Cited passages"}
        >
          {references.map((part, index) => (
            <button
              key={`${part.data.id}-${index}`}
              type="button"
              onClick={() => onReferenceClick(part.data)}
              title={part.data.excerpt}
              aria-label={`Go to passage ${part.data.ref} in the corpus`}
              className="inline-flex cursor-pointer items-center gap-1 rounded-full border bg-background px-2 py-0.5 font-mono text-xs text-muted-foreground outline-none hover:border-amber-400 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60"
            >
              <BookOpen className="size-3" aria-hidden="true" />
              {part.data.ref}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
