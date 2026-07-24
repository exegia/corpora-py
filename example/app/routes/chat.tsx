import { useEffect, useRef, useState } from "react"
import { type MetaDescriptor } from "react-router"
import { MessagesSquare } from "lucide-react"
import { Badge } from "~/components/ui/badge"
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
  // Nothing here is gated on a visitor credential: the corpus list comes
  // from the backend's `GET /storage` (read with the SERVER's own Hub token,
  // same as Explore), the MCP load runs through the backend too, and the
  // assistant itself defaults to the free demo model served through this
  // deployment's /api/gateway proxy. A validated Anthropic key in Settings
  // upgrades the model — inside ChatView, not here.
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

      {phase.name === "select" && (
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

      {phase.name === "loading" && (
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

      {phase.name === "ready" && (
        <ChatView
          key={phase.corpus.filename}
          corpus={phase.corpus}
          onChangeCorpus={backToSelect}
        />
      )}
    </div>
  )
}
