import { useEffect, useState } from "react"
import { API_URL } from "~/lib/types/socket"

/**
 * What the backend this build points at actually permits.
 *
 * `GET /capabilities` (unauthenticated, see `corpora_py.app`) reports two
 * deployment flags the UI can't infer at build time:
 *
 * - `auth_required` -- `AUTH_REQUIRED`. False on the public demo, where a
 *   visitor converts and browses with no Supabase token at all.
 * - `hub_writable` -- the inverse of `HF_READ_ONLY`. False on the public
 *   demo: the Hugging Face repo is read-only, so "Publish to Hugging Face"
 *   would be a button that can only ever 403. Ask, then don't render it.
 *
 * The answer is fetched once per module load and shared by every caller --
 * it's fixed for the lifetime of the deployment, so re-asking per component
 * would be pure noise.
 */
export type Capabilities = {
  authRequired: boolean
  hubWritable: boolean
}

/** What to assume when the backend can't be reached. Writes are hidden rather
 * than offered-and-failing: an unreachable API is not evidence of permission. */
const UNKNOWN: Capabilities = { authRequired: true, hubWritable: false }

let pending: Promise<Capabilities> | null = null

export const fetchCapabilities = (): Promise<Capabilities> => {
  pending ??= fetch(`${API_URL}/capabilities`)
    .then(async (response) => {
      if (!response.ok) return UNKNOWN
      const body = (await response.json()) as {
        auth_required?: boolean
        hub_writable?: boolean
      }
      return {
        authRequired: body.auth_required ?? true,
        hubWritable: body.hub_writable ?? false,
      }
    })
    .catch(() => UNKNOWN)
  return pending
}

/** React view of {@link fetchCapabilities}; `undefined` until it answers. */
export const useCapabilities = (): Capabilities | undefined => {
  const [capabilities, setCapabilities] = useState<Capabilities | undefined>(
    undefined
  )

  useEffect(() => {
    let cancelled = false
    void fetchCapabilities().then((result) => {
      if (!cancelled) setCapabilities(result)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return capabilities
}
