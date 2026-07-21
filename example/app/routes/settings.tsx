import { useState, type FormEvent } from "react"
import type { MetaDescriptor } from "react-router"
import {
  CheckCircle2,
  Info,
  KeyRound,
  Loader2,
  ShieldAlert,
  Sparkles,
  Trash2,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "~/components/reui/alert"
import { HuggingFaceIcon } from "~/components/icons/icon-hugging-face"
import { Badge } from "~/components/ui/badge"
import { Button } from "~/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "~/components/ui/card"
import { Input } from "~/components/ui/input"
import {
  clearApiKey,
  IS_PROD,
  markApiKeyStatus,
  setApiKey,
  useApiKeys,
  validateAnthropicKey,
  validateHfKey,
  validateSupabaseKey,
  type ApiKeyEntry,
  type ApiKeyName,
  type ValidationResult,
} from "~/lib/settings"
import { cn } from "~/lib/utils"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Settings | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" },
  ]
}

/** Chip summarizing the stored key's state, shown next to the section title. */
function KeyStatusBadge({ entry }: { entry: ApiKeyEntry }) {
  if (!entry.value) return <Badge variant="outline">No key set</Badge>
  switch (entry.status) {
    case "valid":
      return (
        <Badge className="bg-emerald-600 text-white dark:bg-emerald-500">
          Valid
        </Badge>
      )
    case "invalid":
      return <Badge variant="destructive">Invalid</Badge>
    default:
      return <Badge variant="secondary">Not yet validated</Badge>
  }
}

type KeySectionProps = {
  name: ApiKeyName
  entry: ApiKeyEntry
  title: string
  icon: React.ReactNode
  description: React.ReactNode
  inputLabel: string
  placeholder: string
  validate: (key: string) => Promise<ValidationResult>
}

/**
 * One settings section: labeled password input + "Save & validate" / "Clear".
 * Saving stores the key in session state first (status "unchecked"), then
 * runs the validator and marks the stored key "valid"/"invalid" -- so a key
 * that fails validation is still updatable/clearable, never wedged.
 */
function KeySection({
  name,
  entry,
  title,
  icon,
  description,
  inputLabel,
  placeholder,
  validate,
}: KeySectionProps) {
  const [draft, setDraft] = useState(entry.value)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<ValidationResult | null>(null)
  const inputId = `${name}-api-key`

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const value = draft.trim()
    if (!value || busy) return
    setBusy(true)
    setFeedback(null)
    setApiKey(name, value)
    const result = await validate(value)
    markApiKeyStatus(name, result.ok ? "valid" : "invalid")
    setFeedback(result)
    setBusy(false)
  }

  const handleClear = () => {
    clearApiKey(name)
    setDraft("")
    setFeedback(null)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {icon}
          {title}
          <KeyStatusBadge entry={entry} />
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <label htmlFor={inputId} className="text-sm font-medium">
            {inputLabel}
          </label>
          <Input
            id={inputId}
            type="password"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={placeholder}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={entry.status === "invalid" || undefined}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="submit"
              disabled={busy || !draft.trim()}
              className="gap-1.5"
              data-cuelume-press
              data-cuelume-release
            >
              {busy ? (
                <Loader2
                  className="size-4 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              ) : (
                <KeyRound className="size-4" aria-hidden="true" />
              )}
              {busy ? "Validating…" : "Save & validate"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={handleClear}
              disabled={busy || (!entry.value && !draft)}
              className="gap-1.5"
              data-cuelume-press
              data-cuelume-release
            >
              <Trash2 className="size-4" aria-hidden="true" />
              Clear key
            </Button>
          </div>

          {feedback && !feedback.ok && (
            <Alert variant="destructive" role="alert">
              <ShieldAlert className="size-4" aria-hidden="true" />
              <AlertTitle>Key validation failed</AlertTitle>
              <AlertDescription>{feedback.message}</AlertDescription>
            </Alert>
          )}
          {feedback?.ok && (
            <p
              className={cn(
                "flex items-center gap-1.5 text-sm",
                "text-emerald-700 dark:text-emerald-400"
              )}
              role="status"
            >
              <CheckCircle2 className="size-4" aria-hidden="true" />
              {feedback.message}
            </p>
          )}
        </form>
      </CardContent>
    </Card>
  )
}

export default function Settings() {
  const keys = useApiKeys()

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">Settings</h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Manage the API keys the app uses. Keys are kept in session state for
          this tab only — they're never written to logs or URLs.
        </p>
      </div>

      <KeySection
        name="hf"
        entry={keys.hf}
        title="Hugging Face API key"
        icon={<HuggingFaceIcon className="size-5" />}
        description={
          <>
            Enables the Explore features for datasets and repositories published
            to the Hugging Face Hub. Until a key is saved and validated, Explore
            stays disabled. Create a token under{" "}
            <a
              href="https://huggingface.co/settings/tokens"
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2"
            >
              Hub settings → Access Tokens
            </a>
            .
          </>
        }
        inputLabel="Enter Hugging Face API key"
        placeholder="hf_…"
        validate={validateHfKey}
      />

      <KeySection
        name="supabase"
        entry={keys.supabase}
        title="Supabase API key"
        icon={<KeyRound className="size-5" aria-hidden="true" />}
        description={
          <>
            From the Supabase dashboard (Settings → API). Sent as a{" "}
            <code>Bearer</code> token on protected backend calls in{" "}
            <strong>production only</strong> — without it, protected calls fail
            in production.
          </>
        }
        inputLabel="Enter Supabase API key"
        placeholder="eyJ…"
        validate={validateSupabaseKey}
      />

      <KeySection
        name="anthropic"
        entry={keys.anthropic}
        title="Anthropic API key"
        icon={<Sparkles className="size-5 text-amber-500" aria-hidden="true" />}
        description={
          <>
            Powers the AI assistant in the corpus viewer&apos;s chat panel: a
            real agent that inspects your corpus&apos;s graph nodes over MCP and
            records node-type corrections. Until a key is saved and validated,
            the chat runs a mock assistant. The key is sent directly from this
            app to Anthropic — create one under{" "}
            <a
              href="https://console.anthropic.com/settings/keys"
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2"
            >
              Anthropic Console → API keys
            </a>
            .
          </>
        }
        inputLabel="Enter Anthropic API key"
        placeholder="sk-ant-…"
        validate={validateAnthropicKey}
      />

      {!IS_PROD && (
        <Alert variant="info" role="note">
          <Info className="size-4" aria-hidden="true" />
          <AlertTitle>Development mode</AlertTitle>
          <AlertDescription>
            Backend authentication is bypassed in development, so the Supabase
            key is optional here. In a production build it's required for every
            protected API call.
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
