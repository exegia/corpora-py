import { useMemo } from "react"
import { useChat } from "@ai-sdk/react"
import {
  DirectChatTransport,
  ToolLoopAgent,
  isStepCount,
  type ChatTransport,
  type UIMessage,
} from "ai"
import { createAnthropic } from "@ai-sdk/anthropic"
import { AlertTriangle, ArrowLeft, X } from "lucide-react"
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "~/components/ai-elements/conversation"
import {
  Message,
  MessageContent,
  MessageResponse,
} from "~/components/ai-elements/message"
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  type PromptInputMessage,
} from "~/components/ai-elements/prompt-input"
import { Shimmer } from "~/components/ai-elements/shimmer"
import { Suggestion, Suggestions } from "~/components/ai-elements/suggestion"
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "~/components/ai-elements/tool"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import { AGENT_MODEL } from "~/components/workspace/use-corpus-chat"
import {
  ANTHROPIC_BROWSER_HEADERS,
  boundFetch,
  getApiKey,
} from "~/lib/settings"
import { corpusDisplayName, type LoadedCorpus } from "./corpus-load"
import { suggestionsFor, welcomeMessage, welcomeText } from "./welcome"

/**
 * The chat phase: a Vercel AI Elements chat over the loaded corpus. The agent
 * (`ToolLoopAgent` + the corpus's MCP tools) runs in-process in the webview
 * against the user's own Anthropic key — `DirectChatTransport` bridges it to
 * `useChat`, so there is no server chat endpoint. The conversation opens with
 * a locally-built assistant message summarizing the loaded corpus plus
 * corpus-specific suggestion chips.
 */

/** Tool-loop ceiling — enough to read a few passages, not run away. */
const MAX_STEPS = 12

const systemPrompt = (corpus: LoadedCorpus): string =>
  `You are the corpus chat assistant inside the Corpora desktop app.

The user has loaded the stored corpus archive "${corpus.filename}" — a
Text-Fabric / Context-Fabric dataset published to the Hugging Face Hub — and
wants to explore and discuss it in plain language.

# Corpus summary (from its manifest and index)

${welcomeText(corpus)}

# Tools

Every tool takes the archive filename "${corpus.filename}":
- corpus_content — read text passages under a section ref, paginated. Your
  primary reading tool; fetch before you quote.
- corpus_index — section structure and node-type counts.
- corpus_manifest_get — manifest metadata.
- corpus_node_get — inspect one graph node (otype, slot span, features, text).
- corpus_node_annotate / corpus_manifest_update — WRITE tools. Only use them
  when the user explicitly asks to record a correction; never annotate
  unprompted.

# Guidelines

- Ground answers in passages actually fetched with corpus_content, and cite
  their section refs (e.g. "Genesis 1:3") when quoting or summarizing.
- Never invent tool arguments or passage text.
- Answer in concise, conversational markdown.
- If a question falls outside this corpus, say so briefly and steer back to
  what the corpus can answer.`

export function ChatView({
  corpus,
  onChangeCorpus,
}: {
  corpus: LoadedCorpus
  onChangeCorpus: () => void
}) {
  const transport = useMemo(() => {
    const anthropic = createAnthropic({
      apiKey: getApiKey("anthropic").value,
      headers: ANTHROPIC_BROWSER_HEADERS,
      fetch: boundFetch,
    })
    const agent = new ToolLoopAgent({
      model: anthropic(AGENT_MODEL),
      instructions: systemPrompt(corpus),
      tools: corpus.tools,
      stopWhen: isStepCount(MAX_STEPS),
    })
    return new DirectChatTransport({
      agent,
      // Surface the real failure (the SDK masks errors as "An error occurred"
      // by default, a server-side precaution that doesn't apply in-process —
      // here the "server" is the user's own webview).
      onError: (error) =>
        error instanceof Error ? error.message : String(error),
    }) as ChatTransport<UIMessage>
  }, [corpus])

  const { messages, sendMessage, status, stop, error, clearError } = useChat({
    id: corpus.filename,
    transport,
    messages: [welcomeMessage(corpus)],
  })

  const suggestions = useMemo(() => suggestionsFor(corpus), [corpus])
  const busy = status === "submitted" || status === "streaming"

  const submit = (message: PromptInputMessage) => {
    const text = message.text.trim()
    if (!text || busy) return
    clearError()
    void sendMessage({ text })
  }

  return (
    <div className="flex h-[calc(100svh-11.5rem)] min-h-96 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate font-medium">{corpusDisplayName(corpus)}</h3>
          <Badge variant="secondary" className="shrink-0 font-mono text-xs">
            {corpus.filename}
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onChangeCorpus}
          className="gap-1.5"
          data-cuelume-press
          data-cuelume-release
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          Change corpus
        </Button>
      </div>

      <Conversation className="rounded-2xl border-2 border-border bg-background">
        <ConversationContent>
          {messages.map((message) => (
            <Message from={message.role} key={message.id}>
              <MessageContent>
                {message.parts.map((part, index) => {
                  if (part.type === "text") {
                    return message.role === "assistant" ? (
                      <MessageResponse key={index}>{part.text}</MessageResponse>
                    ) : (
                      <p key={index} className="whitespace-pre-wrap">
                        {part.text}
                      </p>
                    )
                  }
                  if (part.type === "dynamic-tool") {
                    return (
                      <Tool key={part.toolCallId}>
                        <ToolHeader
                          type="dynamic-tool"
                          toolName={part.toolName}
                          state={part.state}
                        />
                        <ToolContent>
                          {part.input != null && (
                            <ToolInput input={part.input} />
                          )}
                          <ToolOutput
                            output={part.output}
                            errorText={part.errorText}
                          />
                        </ToolContent>
                      </Tool>
                    )
                  }
                  return null
                })}
              </MessageContent>
            </Message>
          ))}
          {status === "submitted" && (
            <Message from="assistant">
              <MessageContent>
                <Shimmer className="text-sm">Thinking…</Shimmer>
              </MessageContent>
            </Message>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      {error != null && (
        <Alert variant="destructive" role="alert">
          <AlertTriangle className="size-4" aria-hidden="true" />
          <AlertTitle>The agent run failed</AlertTitle>
          <AlertDescription className="flex items-start justify-between gap-2">
            <span>{error.message}</span>
            <Button
              variant="ghost"
              size="icon"
              onClick={clearError}
              aria-label="Dismiss error"
            >
              <X className="size-4" aria-hidden="true" />
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {messages.length <= 1 && (
        <Suggestions aria-label="Suggested prompts">
          {suggestions.map((suggestion) => (
            <Suggestion
              key={suggestion}
              suggestion={suggestion}
              onClick={(text) => submit({ text, files: [] })}
              disabled={busy}
            />
          ))}
        </Suggestions>
      )}

      <PromptInput onSubmit={submit}>
        <PromptInputBody>
          <PromptInputTextarea
            placeholder={`Ask about ${corpusDisplayName(corpus)}…`}
          />
        </PromptInputBody>
        <PromptInputFooter className="justify-end">
          <PromptInputSubmit status={status} onStop={stop} />
        </PromptInputFooter>
      </PromptInput>
    </div>
  )
}
