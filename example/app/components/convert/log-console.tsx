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

const TONE_CLASSES: Record<LogTone, string> = {
  info: "text-zinc-400",
  success: "text-emerald-400",
  warning: "text-amber-400",
  error: "text-red-400"
}

const TONE_PREFIX: Record<LogTone, string> = {
  info: ">",
  success: "✓",
  warning: "!",
  error: "✗"
}

interface LogConsoleProps {
  title?: string
  lines: LogLine[]
  /** Current one-line status, announced to screen readers on change. */
  status?: string
  /** Rendered above the log area (e.g. the ProcessingStages list). */
  header?: ReactNode
  className?: string
}

/**
 * Terminal-style processing console: verbose, real log lines under a
 * stage-progress header. Auto-scrolls while new lines arrive, but never
 * fights the user -- scrolling up pauses the follow behavior and shows a
 * "Jump to latest" control instead.
 */
export function LogConsole({ title = "Conversion log", lines, status, header, className }: LogConsoleProps) {
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

  // Follow new lines only while the user is already at (or near) the bottom.
  useEffect(() => {
    if (atBottom) scrollToBottom()
  }, [lines.length, atBottom, scrollToBottom])

  const handleScroll = () => {
    const node = scrollRef.current
    if (!node) return
    setAtBottom(node.scrollHeight - node.scrollTop - node.clientHeight < 24)
  }

  const handleCopy = () => {
    void navigator.clipboard.writeText(lines.map((line) => line.text).join("\n"))
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
        >
          {copied ? (
            <Check className="size-4 text-emerald-400" aria-hidden="true" />
          ) : (
            <Copy className="size-4" aria-hidden="true" />
          )}
        </Button>
      </div>

      {header && <div className="border-b border-zinc-800 px-4 py-3 text-zinc-100">{header}</div>}

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full max-h-80 overflow-y-auto p-4 font-mono text-xs leading-relaxed md:text-sm"
          tabIndex={0}
          role="log"
          aria-label="Processing log"
        >
          {lines.length === 0 && (
            <p className="text-zinc-500">Waiting for an upload…</p>
          )}
          {lines.map((line, index) => (
            <p
              key={`${index}-${line.text}`}
              className="mb-1.5 flex animate-in items-start gap-2 duration-300 fade-in last:mb-0 motion-reduce:animate-none"
            >
              <span className={cn("shrink-0 font-semibold", TONE_CLASSES[line.tone])} aria-hidden="true">
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
