import { useEffect, useRef, useState } from "react"
import { type MetaDescriptor, useNavigate } from "react-router"
import { BubblesIcon, KeyRound, MessagesSquare } from "lucide-react"
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
import { hasValidAnthropicKey, useApiKeys } from "~/lib/settings"

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
  // Picking and loading a corpus needs no visitor credential: the list comes
  // from the backend's `GET /storage` (read with the SERVER's own Hub token,
  // same as Explore) and the MCP load runs through the backend too. Only the
  // assistant itself needs a key -- the app calls the Anthropic API directly
  // from the browser with the user's own key, there is no proxy in between --
  // so the key gates just the final ChatView, not the select/load flow.
  const anthropicReady = hasValidAnthropicKey(keys)

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

      {phase.name === "ready" &&
        (anthropicReady ? (
          <ChatView
            key={phase.corpus.filename}
            corpus={phase.corpus}
            onChangeCorpus={backToSelect}
          />
        ) : (
          // Corpus loaded, assistant locked: the moment a validated key lands
          // in Settings (useApiKeys is live), this flips to the real ChatView
          // with the already-loaded corpus -- no reload, no re-pick.
          <ChatPlaceholder inputPlaceholder="Add your Anthropic API key in Settings to start chatting…">
            <Empty className="border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BubblesIcon className="size-6" aria-hidden="true" />
                </EmptyMedia>
                <EmptyTitle>
                  {filenameToId(phase.corpus.filename)} is loaded — add a key to
                  chat
                </EmptyTitle>
                <EmptyDescription>
                  {keys.anthropic.status === "invalid"
                    ? "The saved Anthropic key failed validation. Update or replace it in Settings to unlock the assistant."
                    : "The assistant runs on the Anthropic API with your own key, straight from this browser. Save and validate one in Settings to start the conversation."}
                </EmptyDescription>
              </EmptyHeader>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  onClick={() => navigate("/settings")}
                  className="gap-1.5"
                  data-cuelume-press
                  data-cuelume-release
                >
                  <KeyRound className="size-4" aria-hidden="true" />
                  Open Settings
                </Button>
                <Button variant="outline" onClick={backToSelect}>
                  Change corpus
                </Button>
              </div>
            </Empty>
          </ChatPlaceholder>
        ))}
    </div>
  )
}
