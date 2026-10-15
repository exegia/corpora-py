import { useAtom, useAtomValue, useSetAtom } from "jotai"
import { Monitor, Radio } from "lucide-react"
import { PanelHeading } from "@/components/heading"
import { Field, FieldHelper, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { nextTheme } from "@/hooks/use-theme"
import { applyRequestTokenAtom, requestTokenAtom, tokenDraftAtom } from "@/shared/store"
import type { WorkspaceViewProps } from "@/lib/workspace-view"

export function SettingsTab({
    backend,
    isActive,
    isAutoEnabled,
    pause,
    resume,
    theme,
    resolvedTheme,
    setTheme
}: WorkspaceViewProps) {
    const requestToken = useAtomValue(requestTokenAtom)
    const applyRequestToken = useSetAtom(applyRequestTokenAtom)
    const [tokenDraft, setTokenDraft] = useAtom(tokenDraftAtom)
    const authLabel =
        backend.authRequired === null ? "Awaiting policy" : backend.authRequired ? "JWT protected" : "Local development"
    return (
        <div>
            <PanelHeading
                eyebrow="Workspace preferences"
                title="Settings">
                Adjust the desktop appearance and inspect your local connection.
            </PanelHeading>
            <div className="flex flex-col gap-4">
                <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-5">
                    <div className="flex items-start gap-3">
                        <Monitor
                            className="mt-0.5 size-4 text-muted-foreground"
                            aria-hidden="true"
                            strokeWidth={1.5}
                        />
                        <div className="flex flex-col gap-1">
                            <h2 className="text-sm font-semibold">Appearance</h2>
                            <p className="text-sm capitalize text-muted-foreground">
                                {theme} theme{theme === "system" ? ` · currently ${resolvedTheme}` : ""}
                            </p>
                            <p className="text-xs text-muted-foreground">Your preference is saved on this device.</p>
                        </div>
                    </div>
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setTheme(nextTheme(theme))}>
                        Use {nextTheme(theme)} theme
                    </Button>
                </section>
                <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-5">
                    <div className="flex items-start gap-3">
                        <Radio
                            className="mt-0.5 size-4 text-muted-foreground"
                            aria-hidden="true"
                            strokeWidth={1.5}
                        />
                        <div className="flex flex-col gap-1">
                            <h2 className="text-sm font-semibold">Connection monitoring</h2>
                            <p className="text-sm text-muted-foreground">
                                {isActive
                                    ? "Retrying the offline sidecar every 3 seconds."
                                    : backend.state === "ready"
                                      ? "Backend online. Automatic checks stop until a manual check observes it offline."
                                      : "Automatic status checks are paused."}
                            </p>
                            <p className="text-xs text-muted-foreground">
                                Pausing checks does not stop Python or any conversion jobs.
                            </p>
                        </div>
                    </div>
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={isAutoEnabled ? pause : resume}>
                        {isAutoEnabled ? "Pause automatic checks" : "Enable automatic checks"}
                    </Button>
                </section>
                <section className="rounded-xl border border-border bg-card p-5">
                    <h2 className="mb-3 text-sm font-semibold">Backend access</h2>
                    <dl className="grid gap-3 text-sm">
                        <dt className="text-muted-foreground">Endpoint</dt>
                        <dd className="select-text break-all font-mono">{backend.url ?? "Not available"}</dd>
                        <dt className="text-muted-foreground">Authentication</dt>
                        <dd>{authLabel}</dd>
                    </dl>
                    <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                        Authentication is configured by the backend environment. Appearance and monitoring preferences
                        do not change its security policy.
                    </p>
                    <form
                        className="mt-5 flex flex-col gap-3"
                        onSubmit={(event) => {
                            event.preventDefault()
                            applyRequestToken(tokenDraft)
                        }}>
                        <Field>
                            <FieldLabel>Supabase request token</FieldLabel>
                            <Input
                                type="password"
                                autoComplete="off"
                                spellCheck={false}
                                value={tokenDraft}
                                onChange={(event) => setTokenDraft(event.target.value)}
                                placeholder="Paste a Supabase JWT"
                            />
                            <FieldHelper>
                                Used only for conversion HTTP requests. Kept in memory, never saved or logged. Applying
                                a different token clears the visible job list.
                            </FieldHelper>
                        </Field>
                        <div className="flex flex-wrap items-center gap-2">
                            <Button
                                type="submit"
                                size="sm"
                                disabled={!tokenDraft.trim()}>
                                Apply token
                            </Button>
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={!requestToken}
                                onClick={() => applyRequestToken("")}>
                                Clear token
                            </Button>
                            <span
                                role="status"
                                className="text-xs text-muted-foreground">
                                {requestToken ? "Request token applied for this session" : "No request token applied"}
                            </span>
                        </div>
                    </form>
                    <p className="mt-3 text-xs text-muted-foreground">
                        Submitted jobs continue on Python when you change tabs; quitting the desktop stops its sidecar.
                    </p>
                </section>
            </div>
        </div>
    )
}
