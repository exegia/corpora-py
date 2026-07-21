import type { ReactNode } from "react"
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "~/components/ai-elements/prompt-input"

/**
 * The chat frame for every phase *before* a corpus is chatting: same
 * dimensions and composer as `ChatView`, but the conversation area centers
 * `children` (the corpus prompt/picker, the loading progress, the key gate)
 * and the prompt input is disabled — the chat visibly exists, it just isn't
 * unlocked yet.
 */
export function ChatPlaceholder({
  inputPlaceholder,
  children,
}: {
  /** Greyed-out composer hint, e.g. "Select a corpus to start chatting…". */
  inputPlaceholder: string
  children: ReactNode
}) {
  return (
    <div className="flex h-[calc(100svh-11.5rem)] min-h-96 flex-col gap-3">
      {/* Spacer standing in for ChatView's header row, so the conversation
          area sits at the same height across phases. */}
      <div className="h-8" aria-hidden="true" />

      <div className="flex flex-1 overflow-y-auto rounded-2xl border-2 border-border bg-background">
        <div className="m-auto w-full max-w-xl p-6">{children}</div>
      </div>

      <PromptInput onSubmit={() => {}} aria-disabled="true">
        <PromptInputBody>
          <PromptInputTextarea disabled placeholder={inputPlaceholder} />
        </PromptInputBody>
        <PromptInputFooter className="justify-end">
          <PromptInputSubmit disabled />
        </PromptInputFooter>
      </PromptInput>
    </div>
  )
}
