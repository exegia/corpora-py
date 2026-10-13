import { ReactNode } from "react"

export function PanelHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
    return (
        <div className="mb-7 flex flex-col gap-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">{eyebrow}</p>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">{children}</p>
        </div>
    )
}
