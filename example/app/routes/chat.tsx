import { useEffect, useRef, useState } from "react"
import { type MetaDescriptor, useNavigate } from "react-router"
import { BubblesIcon, Check, KeyRound, MessagesSquare, X } from "lucide-react"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty"
import {
  ChatPlaceholder,
  ChatView,
  CorpusPicker,
  LoadingProgress,
  closeCorpus,
  loadCorpus,
  type LoadedCorpus,
  type LoadStepId,
} from "~/components/chat"
import { filenameToId } from "~/lib/corpus-detail"
import {
  hasValidAnthropicKey,
  hasValidHfKey,
  useApiKeys,
} from "~/lib/settings"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Chat | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" },
  ]
}

/**
 * The chat route: the chat UI is always on screen, but stays locked (disabled
 * composer, centered prompt) until a published corpus has been picked and
 * loaded into the MCP server — then the conversation opens with a friendly
 * assistant introduction of the loaded corpus.
 *
 * Phase machine: select → loading (per-step progress, retryable on error) →
 * ready (the live chat). "Change corpus" tears the chat down, closes the MCP
 * client, and returns to select.
 */

type Phase =
  | { name: "select" }
  | { name: "loading"; filename: string; step: LoadStepId; error?: string }
  | { name: "ready"; corpus: LoadedCorpus }

export default function Chat() {
  const navigate = useNavigate()
  const keys = useApiKeys()
  const hfReady = hasValidHfKey(keys)
  const anthropicReady = hasValidAnthropicKey(keys)
  const ready = hfReady && anthropicReady

  const [phase, setPhase] = useState<Phase>({ name: "select" })
  // Monotonic token: a stale in-flight load (user navigated back, picked
  // another corpus, or unmounted) sees a newer token and discards itself.
  const loadTokenRef = useRef(0)
  // The open MCP client's owner — closed on unmount / corpus change.
  const corpusRef = useRef<LoadedCorpus | null>(null)

  useEffect(
    () => () => {
      loadTokenRef.current += 1
      if (corpusRef.current) closeCorpus(corpusRef.current)
      corpusRef.current = null
    },
    []
  )

  const startLoad = (filename: string) => {
    const token = ++loadTokenRef.current
    setPhase({ name: "loading", filename, step: "connect" })
    loadCorpus(filename, (step) => {
      if (loadTokenRef.current === token)
        setPhase({ name: "loading", filename, step })
    })
      .then((corpus) => {
        if (loadTokenRef.current !== token) {
          closeCorpus(corpus)
          return
        }
        corpusRef.current = corpus
        setPhase({ name: "ready", corpus })
      })
      .catch((error: unknown) => {
        if (loadTokenRef.current !== token) return
        const message = error instanceof Error ? error.message : String(error)
        setPhase((prev) =>
          prev.name === "loading" ? { ...prev, error: message } : prev
        )
      })
  }

  const backToSelect = () => {
    loadTokenRef.current += 1
    if (corpusRef.current) closeCorpus(corpusRef.current)
    corpusRef.current = null
    setPhase({ name: "select" })
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">
          Chat{" "}
          <Badge variant="secondary" className="py-1.5 text-xl">
            .corpus
          </Badge>
        </h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Pick a published corpus, load it into the MCP server, and explore it
          conversationally with the AI assistant.
        </p>
      </div>

      {!ready && (
        <ChatPlaceholder inputPlaceholder="Add your API keys in Settings to start chatting…">
          <Empty className="border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BubblesIcon className="size-6" aria-hidden="true" />
              </EmptyMedia>
              <EmptyTitle>API keys required</EmptyTitle>
              <EmptyDescription>
                Chat needs a validated Hugging Face key (to list the published
                corpora) and a validated Anthropic key (to run the assistant).
              </EmptyDescription>
            </EmptyHeader>
            <ul
              className="flex flex-col gap-1 text-sm"
              aria-label="Key status"
            >
              {(
                [
                  ["Hugging Face", hfReady],
                  ["Anthropic", anthropicReady],
                ] as const
              ).map(([label, ok]) => (
                <li key={label} className="flex items-center gap-2">
                  {ok ? (
                    <Check
                      className="size-4 text-green-600"
                      aria-hidden="true"
                    />
                  ) : (
                    <X className="size-4 text-destructive" aria-hidden="true" />
                  )}
                  {label} key {ok ? "ready" : "missing or unvalidated"}
                </li>
              ))}
            </ul>
            <Button
              onClick={() => navigate("/settings")}
              className="gap-1.5"
              data-cuelume-press
              data-cuelume-release
            >
              <KeyRound className="size-4" aria-hidden="true" />
              Open Settings
            </Button>
          </Empty>
        </ChatPlaceholder>
      )}

      {ready && phase.name === "select" && (
        <ChatPlaceholder inputPlaceholder="Select a corpus to start chatting…">
          <div className="flex flex-col gap-5">
            <div className="flex flex-col items-center gap-2 text-center">
              <div className="flex size-10 items-center justify-center rounded-full bg-muted">
                <MessagesSquare
                  className="size-5 text-muted-foreground"
                  aria-hidden="true"
                />
              </div>
              <h3 className="font-medium">Select a corpus to begin</h3>
              <p className="text-sm text-muted-foreground">
                The chat unlocks once a corpus is loaded — pick one of the
                published archives below.
              </p>
            </div>
            <CorpusPicker onSelect={startLoad} />
          </div>
        </ChatPlaceholder>
      )}

      {ready && phase.name === "loading" && (
        <ChatPlaceholder
          inputPlaceholder={`Loading ${filenameToId(phase.filename)}…`}
        >
          <LoadingProgress
            filename={phase.filename}
            step={phase.step}
            error={phase.error}
            onRetry={() => startLoad(phase.filename)}
            onBack={backToSelect}
          />
        </ChatPlaceholder>
      )}

      {ready && phase.name === "ready" && (
        <ChatView
          key={phase.corpus.filename}
          corpus={phase.corpus}
          onChangeCorpus={backToSelect}
        />
      )}
    </div>
  )
}
