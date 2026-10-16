import { useMemo } from "react"
import { useAtomValue, useSetAtom } from "jotai"
import { PanelRight, Sidebar } from "lucide-react"
import { PanelPlugin } from "@/components/panel-plugin"
import { Accordion } from "@/components/ui/accordion"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { panelPluginRegistry, type PanelPluginArea } from "@/lib/panel"
import { panelActionAtom, pluginPlacementsAtom } from "@/shared/store"

export function WorkspacePanel({ area }: { area: PanelPluginArea }) {
    const placements = useAtomValue(pluginPlacementsAtom)
    const dispatch = useSetAtom(panelActionAtom)
    const plugins = placements.filter((placement) => placement.area === area)
    const available = panelPluginRegistry.plugins.filter(
        (definition) => !placements.some((placement) => placement.id === definition.id)
    )

    const isOpen = useMemo(() => {
        return plugins.filter((plugin) => plugin.expanded).map((plugin) => plugin.id)
    }, [plugins, available])

    function hidePanel() {
        dispatch({ type: "set-open", area, open: false })
        requestAnimationFrame(() => {
            document.querySelector<HTMLButtonElement>(`[data-panel-toggle="${area}"]`)?.focus()
        })
    }

    return (
        <div className="flex h-full min-h-0 flex-col">
            <header className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
                {area === "inspector" && (
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`Hide ${area}`}
                        onClick={hidePanel}>
                        <PanelRight aria-hidden="true" />
                    </Button>
                )}
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{area}</h2>
                {area === "sidebar" && (
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label="Shrink sidebar"
                        onClick={hidePanel}>
                        <Sidebar aria-hidden="true" />
                    </Button>
                )}
            </header>
            <ScrollArea scrollFade className="min-h-0 flex-1">
                <Accordion
                    multiple
                    value={isOpen}
                    onValueChange={(ids) => dispatch({ type: "set-expanded", area, ids })}>
                    {plugins.map((placement, index) => {
                        const definition = panelPluginRegistry.getPlugin(placement.id)
                        if (!definition) return null
                        const Component = definition.component
                        return (
                            <PanelPlugin
                                key={`${placement.id}-${index}`}
                                id={placement.id}
                                name={definition.name}
                                area={area}
                                expanded={placement.expanded}>
                                <Component
                                    id={placement.id}
                                    name={definition.name}
                                    area={area}
                                />
                            </PanelPlugin>
                        )
                    })}
                </Accordion>
                {!plugins.length && <p className="p-3 text-xs text-muted-foreground">Add a plugin to this panel.</p>}
            </ScrollArea>
        </div>
    )
}
