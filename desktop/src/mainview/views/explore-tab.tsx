import { PanelHeading } from "@/components/heading"
import { Button } from "@/components/ui/button"
import type { TabID } from "@/shared/navigation"
import { Compass } from "lucide-react"

export interface ExploreTabProps {
    onNavigate: (id: TabID) => void
}

export function ExploreTab({ onNavigate }: ExploreTabProps) {
    return (
        <>
            <PanelHeading
                eyebrow="Texts & collections"
                title="Corpus explorer">
                A dedicated space to inspect the structure and content of your corpora.
            </PanelHeading>
            <section className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card p-8 text-center">
                <Compass
                    className="mb-2 size-8 text-muted-foreground"
                    aria-hidden="true"
                    strokeWidth={1.5}
                />
                <h2 className="text-base font-semibold">A place for your texts</h2>
                <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
                    Library browsing is not connected to this view yet. No collections have been loaded or counted.
                </p>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onNavigate("tab:home")}>
                    Back to dashboard
                </Button>
            </section>
        </>
    )
}
