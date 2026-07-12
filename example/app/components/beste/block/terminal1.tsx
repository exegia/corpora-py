"use client"

import { Check, Copy, LoaderCircle, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import { cn } from "~/lib/utils"

interface TerminalCommand {
  id: string
  prompt?: string
  command: string
  output?: string
  outputDelay?: number
}

interface Terminal1Props {
  badge?: {
    label: string
    variant?: "default" | "secondary" | "outline"
  }
  heading?: string
  description?: string
  terminal?: {
    title?: string
    commands: TerminalCommand[]
    typeSpeed?: number
    delayBetweenCommands?: number
    showLineNumbers?: boolean
    showControls?: boolean
  }
  showCopyButton?: boolean
  glowEffect?: boolean
  className?: string
  logs?: string[]
  status?: string
  progress?: number
  isRunning?: boolean
}

export const terminal1Demo: Terminal1Props = {
  badge: { label: "Quick Start", variant: "secondary" },
  heading: "Get started in seconds",
  description:
    "Install our CLI and start building. Just a few commands to get up and running.",
  terminal: {
    title: "Terminal",
    commands: [
      {
        id: "cmd-1",
        prompt: "$ ",
        command: "npm install -g @acme/cli",
        output: "Installing @acme/cli...\n✓ Installed successfully",
        outputDelay: 800
      },
      {
        id: "cmd-2",
        prompt: "$ ",
        command: "acme init my-project",
        output: "Creating project structure...\n✓ Project initialized",
        outputDelay: 600
      },
      {
        id: "cmd-3",
        prompt: "$ ",
        command: "cd my-project && acme dev",
        output:
          "Starting development server...\n✓ Ready at http://localhost:3000",
        outputDelay: 500
      }
    ],
    typeSpeed: 50,
    delayBetweenCommands: 1000,
    showLineNumbers: false
  },
  showCopyButton: true,
  glowEffect: true
}

interface TypewriterState {
  commandIndex: number
  charIndex: number
  outputCharIndex: number
  isTypingCommand: boolean
  isTypingOutput: boolean
  isComplete: boolean
}

function useTerminalTypewriter(
  commands: TerminalCommand[],
  typeSpeed = 50,
  outputTypeSpeed = 10,
  delayBetweenCommands = 1000,
  isInView = true
) {
  const [state, setState] = useState<TypewriterState>({
    commandIndex: 0,
    charIndex: 0,
    outputCharIndex: 0,
    isTypingCommand: true,
    isTypingOutput: false,
    isComplete: false
  })
  const [displayedCommands, setDisplayedCommands] = useState<
    Array<{ command: string; output: string; isComplete: boolean }>
  >([])
  const [isStarted, setIsStarted] = useState(false)

  const reset = useCallback(() => {
    setState({
      commandIndex: 0,
      charIndex: 0,
      outputCharIndex: 0,
      isTypingCommand: true,
      isTypingOutput: false,
      isComplete: false
    })
    setDisplayedCommands([])
    setIsStarted(false)
  }, [])

  useEffect(() => {
    if (isInView && !isStarted) {
      setIsStarted(true)
    }
  }, [isInView, isStarted])

  useEffect(() => {
    if (!isStarted || !commands || commands.length === 0 || state.isComplete)
      return

    const currentCommand = commands[state.commandIndex]
    if (!currentCommand) return

    // Typing command
    if (state.isTypingCommand) {
      if (state.charIndex < currentCommand.command.length) {
        const timeout = setTimeout(() => {
          setState((prev) => ({ ...prev, charIndex: prev.charIndex + 1 }))

          setDisplayedCommands((prev) => {
            const updated = [...prev]
            const existing = updated[state.commandIndex] || {
              command: "",
              output: "",
              isComplete: false
            }
            updated[state.commandIndex] = {
              command: currentCommand.command.slice(0, state.charIndex + 1),
              output: existing.output,
              isComplete: false
            }
            return updated
          })
        }, typeSpeed)
        return () => clearTimeout(timeout)
      } else {
        // Command finished, start output after delay
        const outputDelay = currentCommand.outputDelay ?? 500
        const timeout = setTimeout(() => {
          setState((prev) => ({
            ...prev,
            isTypingCommand: false,
            isTypingOutput: !!currentCommand.output,
            outputCharIndex: 0
          }))
        }, outputDelay)
        return () => clearTimeout(timeout)
      }
    }

    // Typing output
    if (state.isTypingOutput && currentCommand.output) {
      if (state.outputCharIndex < currentCommand.output.length) {
        const timeout = setTimeout(() => {
          setState((prev) => ({
            ...prev,
            outputCharIndex: prev.outputCharIndex + 1
          }))

          setDisplayedCommands((prev) => {
            const updated = [...prev]
            const existing = updated[state.commandIndex] || {
              command: "",
              output: "",
              isComplete: false
            }
            updated[state.commandIndex] = {
              command: existing.command,
              output:
                currentCommand.output?.slice(0, state.outputCharIndex + 1) ||
                "",
              isComplete: false
            }
            return updated
          })
        }, outputTypeSpeed)
        return () => clearTimeout(timeout)
      } else {
        // Output finished
        setDisplayedCommands((prev) => {
          const updated = [...prev]
          const existing = updated[state.commandIndex] || {
            command: "",
            output: "",
            isComplete: false
          }
          updated[state.commandIndex] = {
            command: existing.command,
            output: currentCommand.output || "",
            isComplete: true
          }
          return updated
        })
        setState((prev) => ({ ...prev, isTypingOutput: false }))
      }
    }

    // Move to next command or finish
    if (!state.isTypingCommand && !state.isTypingOutput) {
      if (state.commandIndex < commands.length - 1) {
        const timeout = setTimeout(() => {
          setState((prev) => ({
            ...prev,
            commandIndex: prev.commandIndex + 1,
            charIndex: 0,
            outputCharIndex: 0,
            isTypingCommand: true,
            isTypingOutput: false
          }))
        }, delayBetweenCommands)
        return () => clearTimeout(timeout)
      } else {
        setState((prev) => ({ ...prev, isComplete: true }))
      }
    }
  }, [
    state,
    commands,
    typeSpeed,
    outputTypeSpeed,
    delayBetweenCommands,
    isStarted
  ])

  return {
    displayedCommands,
    currentCommandIndex: state.commandIndex,
    isTypingCommand: state.isTypingCommand && !state.isComplete,
    isTypingOutput: state.isTypingOutput && !state.isComplete,
    isComplete: state.isComplete,
    reset
  }
}

const terminalTheme = {
  bg: "#09090b", // zinc-900
  border: "#3f3f46", // zinc-700
  header: "#27272a", // zinc-800
  headerText: "#a1a1aa", // zinc-400
  text: "#f4f4f5", // zinc-100
  prompt: "#34d399", // emerald-400
  output: "#a1a1aa", // zinc-400
  glow: "0 0 50px rgba(0,0,0,0.5)"
}

function useInView(
  ref: React.RefObject<HTMLElement | null>,
  options?: { amount?: number }
) {
  const [isInView, setIsInView] = useState(false)

  useEffect(() => {
    if (!ref.current) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setIsInView(true)
        }
      },
      { threshold: options?.amount ?? 0.3 }
    )

    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [ref, options?.amount])

  return isInView
}

export function Terminal1({
                            badge,
                            heading,
                            description,
                            terminal,
                            showCopyButton = true,
                            glowEffect = true,
                            className,
                            logs,
                            status,
                            progress,
                            isRunning = false
                          }: Terminal1Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const isInView = useInView(containerRef, { amount: 0.3 })
  const [copied, setCopied] = useState(false)

  const {
    displayedCommands,
    isTypingCommand,
    isTypingOutput,
    isComplete,
    reset
  } = useTerminalTypewriter(
    terminal?.commands || [],
    terminal?.typeSpeed || 50,
    15,
    terminal?.delayBetweenCommands || 1000,
    isInView
  )

  const handleCopy = useCallback(() => {
    const allCommands = logs
      ? logs.join("\n")
      : terminal?.commands
        .map((cmd) => `${cmd.prompt || "$ "}${cmd.command}`)
        .join("\n")

    if (allCommands) {
      navigator.clipboard.writeText(allCommands)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [logs, terminal?.commands])

  const handleRestart = useCallback(() => {
    reset()
  }, [reset])

  return (
    <section className={cn("h-full w-full", className)}>
      <div className="mx-auto h-full max-w-4xl">
        <div className="flex h-full flex-col items-center justify-center gap-4">
          {badge && (
            <div>
              <Badge variant={badge.variant ?? "default"}>{badge.label}</Badge>
            </div>
          )}

          {heading && (
            <h2 className="text-center text-2xl font-semibold md:text-4xl">
              {heading}
            </h2>
          )}

          {description && (
            <p className="max-w-3xl text-center text-base text-balance text-muted-foreground md:text-lg">
              {description}
            </p>
          )}

          <div ref={containerRef} className="h-full w-full">
            <div
              className="h-full overflow-hidden rounded-lg"
              style={{
                backgroundColor: terminalTheme.bg,
                border: `1px solid ${terminalTheme.border}`,
                boxShadow: glowEffect ? terminalTheme.glow : undefined
              }}
            >
              {/* Header with 3-column grid for centered title */}
              <div
                className="grid grid-cols-3 items-center px-4 py-3"
                style={{ backgroundColor: terminalTheme.header }}
              >
                {/* Left: Window controls */}

                <div
                  className={cn(
                    "flex items-center gap-2",
                    terminal?.showControls && "visible",
                    "invisible"
                  )}
                >
                  <div className="h-3 w-3 rounded-full bg-[#ff5f56]" />
                  <div className="h-3 w-3 rounded-full bg-[#ffbd2e]" />
                  <div className="h-3 w-3 rounded-full bg-[#27c93f]" />
                </div>

                {/* Center: Title (always centered) */}
                <span
                  className="text-center text-sm font-medium"
                  style={{ color: terminalTheme.headerText }}
                >
                  {terminal?.title || "Terminal"}
                </span>

                {/* Right: Action buttons */}
                <div className="flex items-center justify-end gap-2">
                  {showCopyButton && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Copy commands"
                      onClick={handleCopy}
                      className="h-6 w-6 rounded-md transition-colors hover:bg-white/10"
                      style={{ color: terminalTheme.headerText }}
                      title="Copy commands"
                    >
                      {copied ? (
                        <Check className="size-4 text-emerald-400" />
                      ) : (
                        <Copy className="size-4" />
                      )}
                    </Button>
                  )}
                  {isComplete && logs === undefined && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={handleRestart}
                      aria-label="Restart animation"
                      className="h-6 w-6 rounded-md transition-colors hover:bg-white/10"
                      style={{ color: terminalTheme.headerText }}
                      title="Restart animation"
                    >
                      <RotateCcw className="size-4" />
                    </Button>
                  )}
                </div>
              </div>

              <div className="h-full p-4 font-mono text-sm md:p-6 md:text-base">
                {logs !== undefined &&
                  logs.map((line, index) => (
                    <div
                      key={`${index}-${line}`}
                      className="mb-2 flex animate-in items-start gap-2 duration-300 fade-in slide-in-from-bottom-1 last:mb-0 motion-reduce:animate-none"
                    >
                      <span
                        className="font-semibold"
                        style={{ color: terminalTheme.prompt }}
                      >
                        &gt;
                      </span>
                      <span
                        className="whitespace-pre-wrap"
                        style={{ color: terminalTheme.output }}
                      >
                        {line}
                      </span>
                    </div>
                  ))}
                {logs !== undefined && isRunning && (
                  <section
                    className="mt-3 grid animate-in gap-2 border-t border-white/10 pt-3 duration-300 fade-in motion-reduce:animate-none"
                    role="status"
                    aria-live="polite"
                  >
                    <p className="flex items-center gap-2">
                      <LoaderCircle
                        className="size-4 animate-spin motion-reduce:animate-none"
                        style={{ color: terminalTheme.prompt }}
                        aria-hidden="true"
                      />
                      <span style={{ color: terminalTheme.text }}>
                        {status || "Conversion in progress"}
                      </span>
                      <span className="flex gap-1" aria-hidden="true">
                        {[0, 1, 2].map((dot) => (
                          <span
                            key={dot}
                            className="size-1 animate-bounce rounded-full bg-emerald-400 motion-reduce:animate-none"
                            style={{ animationDelay: `${dot * 150}ms` }}
                          />
                        ))}
                      </span>
                    </p>
                    <span
                      className="block h-1 overflow-hidden rounded-full bg-white/10"
                      role="progressbar"
                      aria-label="Conversion progress"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={progress}
                    >
                      <span
                        className="block h-full rounded-full bg-emerald-400 transition-[width] duration-700 ease-out"
                        style={{
                          width: `${Math.min(100, Math.max(6, progress ?? 6))}%`
                        }}
                      />
                    </span>
                  </section>
                )}
                {logs !== undefined && logs.length === 0 && !isRunning && (
                  <div className="flex items-center gap-2">
                    <span
                      className="font-semibold"
                      style={{ color: terminalTheme.prompt }}
                    >
                      &gt;
                    </span>
                    <span style={{ color: terminalTheme.output }}>
                      {status || "Waiting for an upload"}
                    </span>
                    {status && (
                      <span
                        className="animate-pulsing animate-duration-fast"
                        style={{ color: terminalTheme.text }}
                      >
                        |
                      </span>
                    )}
                  </div>
                )}
                {logs === undefined &&
                  displayedCommands.map((item, index) => {
                    const command = terminal?.commands[index]
                    const isCurrentCommand =
                      index === displayedCommands.length - 1
                    return (
                      <div
                        key={command?.id || index}
                        className="mb-3 last:mb-0"
                      >
                        <div className="flex items-start gap-2">
                          {terminal?.showLineNumbers && (
                            <span
                              className="w-6 text-right select-none"
                              style={{ color: terminalTheme.output }}
                            >
                              {index + 1}
                            </span>
                          )}
                          <span
                            className="font-semibold"
                            style={{ color: terminalTheme.prompt }}
                          >
                            {command?.prompt || "$ "}
                          </span>
                          <span style={{ color: terminalTheme.text }}>
                            {item.command}
                            {isCurrentCommand && isTypingCommand && (
                              <span className="animate-pulsing animate-duration-fast">
                                |
                              </span>
                            )}
                          </span>
                        </div>
                        {item.output && (
                          <div
                            className={cn(
                              "mt-1 whitespace-pre-wrap",
                              terminal?.showLineNumbers && "ml-8"
                            )}
                            style={{ color: terminalTheme.output }}
                          >
                            {item.output}
                            {isCurrentCommand && isTypingOutput && (
                              <span className="animate-pulsing animate-duration-fast">
                                |
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                {logs === undefined && displayedCommands.length === 0 && (
                  <div className="flex items-center gap-2">
                    <span
                      className="font-semibold"
                      style={{ color: terminalTheme.prompt }}
                    >
                      {terminal?.commands[0]?.prompt || "$ "}
                    </span>
                    <span
                      className="animate-pulsing animate-duration-fast"
                      style={{ color: terminalTheme.text }}
                    >
                      |
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
