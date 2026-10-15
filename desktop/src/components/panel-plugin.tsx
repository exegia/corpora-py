import { useLayoutEffect, useRef } from "react"
import { AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import type { IPanelPluginProps } from "@/lib/panel"

export function PanelPlugin({ id, name, children, expanded }: IPanelPluginProps & { expanded: boolean }) {
    const item = useRef<HTMLDivElement>(null)
    const trigger = useRef<HTMLButtonElement>(null)
    useLayoutEffect(() => {
        if (!expanded && item.current?.contains(document.activeElement)) trigger.current?.focus()
    }, [expanded])
    return (
        <AccordionItem
            ref={item}
            value={id}
            data-plugin-id={id}
            className="border-b border-border">
            <AccordionTrigger
                ref={trigger}
                className="min-w-0 px-3 py-3 text-xs hover:no-underline">
                {name}
            </AccordionTrigger>

            <AccordionContent
                keepMounted
                className="px-3 pb-3">
                {children}
            </AccordionContent>
        </AccordionItem>
    )
}
