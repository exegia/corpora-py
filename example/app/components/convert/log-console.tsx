"use client"

import { ArrowDown, Check, Copy } from "lucide-react"
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { Button } from "~/components/ui/button"
import { cn } from "~/lib/utils"

export type LogTone = "info" | "success" | "warning" | "error"

export type LogLine = {
  text: string
  tone: LogTone
}

export const TONE_CLASSES: Record<LogTone, string> = {
  info: "text-zinc-400",
  success: "text-emerald-400",
  warning: "text-amber-400",
  error: "text-red-400"
}

export const TONE_PREFIX: Record<LogTone, string> = {
  info: ">",
  success: "✓",
  warning: "!",
  error: "✗"
}

interface LogConsoleProps {
  title?: string
  /**
   * Final completion message lines (success or error) -- the per-stage log
   * lines live inside the stage timeline passed as `header`.
   */
  lines: LogLine[]
  /** Current one-line status, announced to screen readers on change. */
  status?: string
  /** The stage timeline, rendered inside the scroll area above `lines`. */
  header?: ReactNode
  /**
   * Bumps whenever any log content (including per-stage lines inside
   * `header`) grows, so auto-scroll can follow output it doesn't render
   * itself.
   */
  scrollKey?: number
  /** Full text placed on the clipboard by the copy button. */
  copyText?: string
  className?: string
}

/**
 * Terminal-style processing console: the stage timeline (with its inline
 * log lines) scrolls in the body, and the bottom block carries only the
 * final success/error completion message. Auto-scrolls while new output
 * arrives, but never fights the user -- scrolling up pauses the follow
 * behavior and shows a "Jump to latest" control instead.
 */
export function LogConsole({
                             title = "Conversion log",
                             lines,
                             status,
                             header,
                             scrollKey = 0,
                             copyText,
                             className
                           }: LogConsoleProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [copied, setCopied] = useState(false)

  const scrollToBottom = useCallback((smooth = true) => {
    const node = scrollRef.current
    if (!node) return
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    node.scrollTo({
      top: node.scrollHeight,
      behavior: smooth && !reduceMotion ? "smooth" : "auto"
    })
  }, [])

  // Follow new output only while the user is already at (or near) the bottom.
  useEffect(() => {
    if (atBottom) scrollToBottom()
  }, [scrollKey, lines.length, atBottom, scrollToBottom])

  const handleScroll = () => {
    const node = scrollRef.current
    if (!node) return
    setAtBottom(node.scrollHeight - node.scrollTop - node.clientHeight < 24)
  }

  const handleCopy = () => {
    const text = copyText ?? lines.map((line) => line.text).join("\n")
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section
      className={cn(
        "flex h-full min-h-72 flex-col overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950",
        className
      )}
      aria-label={title}
    >
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4 py-2.5">
        <span className="text-sm font-medium text-zinc-400">{title}</span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Copy log"
          title="Copy log"
          onClick={handleCopy}
          className="size-6 rounded-md text-zinc-400 hover:bg-white/10 hover:text-zinc-200"
          data-cuelume-press
          data-cuelume-release
        >
          {copied ? (
            <Check className="size-4 text-emerald-400" aria-hidden="true" />
          ) : (
            <Copy className="size-4" aria-hidden="true" />
          )}
        </Button>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full max-h-96 overflow-y-auto"
          tabIndex={0}
          role="log"
          aria-label="Processing log"
        >
          {header && <div className="px-4 py-3 text-zinc-100">{header}</div>}

          {lines.length > 0 && (
            <div className="border-t border-zinc-800 p-4 font-mono text-xs leading-relaxed md:text-sm">
              {lines.map((line, index) => (
                <p
                  key={`${index}-${line.text}`}
                  className="mb-1.5 flex animate-in items-start gap-2 duration-300 fade-in last:mb-0 motion-reduce:animate-none"
                >
                  <span
                    className={cn("shrink-0 font-semibold", TONE_CLASSES[line.tone])}
                    aria-hidden="true"
                  >
                    {TONE_PREFIX[line.tone]}
                  </span>
                  {/* Tone is also in the text for screen readers, not color alone. */}
                  <span className="sr-only">
                    {line.tone !== "info" ? `${line.tone}: ` : ""}
                  </span>
                  <span
                    className={cn(
                      "whitespace-pre-wrap",
                      line.tone === "info" ? "text-zinc-300" : TONE_CLASSES[line.tone]
                    )}
                  >
                    {line.text}
                  </span>
                </p>
              ))}
            </div>
          )}
        </div>

        {!atBottom && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setAtBottom(true)
              scrollToBottom()
            }}
            className="absolute bottom-3 left-1/2 -translate-x-1/2 gap-1 rounded-full shadow-md"
          >
            <ArrowDown className="size-3.5" aria-hidden="true" />
            Jump to latest
          </Button>
        )}
      </div>

      {status && (
        <div
          className="border-t border-zinc-800 px-4 py-2 text-xs text-zinc-400"
          role="status"
          aria-live="polite"
        >
          {status}
        </div>
      )}
    </section>
  )
}
