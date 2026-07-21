import {
  useCallback,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react"
import { MessageSquareText } from "lucide-react"
import { Button } from "~/components/ui/button"
import { cn } from "~/lib/utils"

import { useWorkspace } from "./workspace-context"

/**
 * Split-screen shell for the corpus workspace.
 *
 * Desktop (lg+): reader | draggable separator | chat, defaulting to a 60/40
 * split. The separator is a keyboard-operable ARIA separator (arrows resize,
 * Home/End jump to the limits, double-click resets). Collapsing the chat gives
 * the reader the full width and leaves a slim "Open chat" affordance.
 *
 * Mobile (<lg): the panes stack vertically — reader first, chat below with a
 * fixed height and internal scrolling — and the separator is hidden.
 *
 * Layout state (split %, collapsed) is ephemeral UI state only.
 */

const MIN_PERCENT = 35
const MAX_PERCENT = 75
const DEFAULT_PERCENT = 60
const KEYBOARD_STEP = 2

const clamp = (value: number): number =>
  Math.min(MAX_PERCENT, Math.max(MIN_PERCENT, value))

export function SplitWorkspace({
  reader,
  chat,
}: {
  reader: ReactNode
  chat: ReactNode
}) {
  const { chatOpen, setChatOpen } = useWorkspace()
  const [percent, setPercent] = useState(DEFAULT_PERCENT)
  const [dragging, setDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    setDragging(true)
  }, [])

  const onPointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (!dragging) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect || rect.width === 0) return
      setPercent(clamp(((event.clientX - rect.left) / rect.width) * 100))
    },
    [dragging]
  )

  const onPointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
    setDragging(false)
  }, [])

  const onSeparatorKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      switch (event.key) {
        case "ArrowLeft":
          setPercent((prev) => clamp(prev - KEYBOARD_STEP))
          break
        case "ArrowRight":
          setPercent((prev) => clamp(prev + KEYBOARD_STEP))
          break
        case "Home":
          setPercent(MIN_PERCENT)
          break
        case "End":
          setPercent(MAX_PERCENT)
          break
        default:
          return
      }
      event.preventDefault()
    },
    []
  )

  return (
    <div
      ref={containerRef}
      style={{ "--reader-pct": `${percent}%` } as CSSProperties}
      className={cn(
        "flex w-full flex-col gap-4 lg:flex-row lg:items-start lg:gap-0",
        dragging && "select-none"
      )}
    >
      <div
        id="corpus-reader-pane"
        className={cn(
          "w-full min-w-0",
          chatOpen ? "lg:w-[var(--reader-pct)]" : "lg:flex-1 lg:pr-3"
        )}
      >
        {reader}
      </div>

      {chatOpen && (
        <div
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label="Resize corpus and chat panels"
          aria-controls="corpus-reader-pane"
          aria-valuemin={MIN_PERCENT}
          aria-valuemax={MAX_PERCENT}
          aria-valuenow={Math.round(percent)}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onDoubleClick={() => setPercent(DEFAULT_PERCENT)}
          onKeyDown={onSeparatorKeyDown}
          className="group hidden shrink-0 cursor-col-resize touch-none items-center justify-center self-stretch rounded px-1.5 outline-none focus-visible:ring-2 focus-visible:ring-ring/60 lg:flex"
        >
          <div
            aria-hidden="true"
            className={cn(
              "h-full min-h-40 rounded-full bg-border transition-colors group-hover:w-0.5 group-hover:bg-ring group-focus-visible:w-0.5 group-focus-visible:bg-ring",
              dragging && "w-0.5 bg-ring"
            )}
          />
        </div>
      )}

      <div
        className={cn(
          // self-stretch (not items-start) so this column spans the full row
          // height — the sticky child below needs the room to pin while the
          // (usually much taller) reader column scrolls.
          "w-full min-w-0 lg:self-stretch",
          chatOpen ? "lg:flex-1" : "lg:w-auto lg:shrink-0"
        )}
      >
        {chatOpen ? (
          <div className="h-[70svh] lg:sticky lg:top-20 lg:h-[calc(100svh-6.5rem)]">
            {chat}
          </div>
        ) : (
          <div className="lg:sticky lg:top-20">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setChatOpen(true)}
              aria-expanded={false}
              aria-controls="chat-panel"
              className="w-full gap-1.5 lg:w-auto"
              data-cuelume-press
              data-cuelume-release
            >
              <MessageSquareText className="size-4" aria-hidden="true" />
              Open chat
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
