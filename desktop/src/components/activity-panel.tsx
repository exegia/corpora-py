import { Terminal, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { BackendEvent } from "@/lib/backend-events"

interface ActivityPanelProps {
    events: BackendEvent[]
    onClear: () => void
    onClose: () => void
    fill?: boolean
}

export function ActivityPanel({ events, onClear, onClose, fill = false }: ActivityPanelProps) {
    return (
        <section id="workspace-events" aria-labelledby="events-heading" className={cn("flex flex-col border-t border-border bg-card", fill ? "h-full min-h-0" : "max-h-60 shrink-0")}>
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-5 py-2">
                <div className="flex items-center gap-2">
                    <Terminal className="size-3.5 text-muted-foreground" aria-hidden="true" strokeWidth={1.5} />
                    <h2 id="events-heading" className="text-xs font-semibold">Connection events</h2>
                    <span className="hidden text-xs text-muted-foreground sm:inline">This session · latest 50</span>
                </div>
                <div className="flex items-center gap-1">
                    <Button type="button" variant="ghost" size="xs" onClick={onClear} disabled={events.length === 0}>Clear</Button>
                    <Button type="button" variant="ghost" size="icon-xs" aria-label="Close connection events" onClick={onClose}><X aria-hidden="true" /></Button>
                </div>
            </header>
            <div className={cn("overflow-y-auto px-5 py-2 select-text [&_*]:select-text", fill && "min-h-0 flex-1")}>
                {events.length === 0 ? <p className="py-5 text-xs text-muted-foreground">No events. Backend state changes will appear here.</p> : (
                    <ol className="flex flex-col gap-1">
                        {events.map(event => (
                            <li key={event.id} className="flex items-baseline gap-3 py-1 font-mono text-xs">
                                <time dateTime={new Date(event.timestamp).toISOString()} className="shrink-0 tabular-nums text-muted-foreground">{new Date(event.timestamp).toLocaleTimeString()}</time>
                                <span className={cn("w-14 shrink-0 uppercase text-muted-foreground", event.level === "error" && "text-destructive-foreground", event.level === "warning" && "text-warning-foreground", event.level === "success" && "text-success-foreground")}>{event.level}</span>
                                <span className="min-w-0 break-words text-foreground">{event.message}</span>
                            </li>
                        ))}
                    </ol>
                )}
            </div>
        </section>
    )
}
