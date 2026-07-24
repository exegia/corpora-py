import { createGateway } from "ai"
import { createAnthropic } from "@ai-sdk/anthropic"
import {
  ANTHROPIC_BROWSER_HEADERS,
  boundFetch,
  getApiKey,
} from "~/lib/settings"

/**
 * The one place that decides which model an in-browser agent runs on. Both
 * chats (the `/chat` route's `ChatView` and the corpus workspace's
 * `useCorpusChat`) pick per run:
 *
 * - **Own key** — a validated Anthropic key in Settings: {@link AGENT_MODEL},
 *   called directly from the browser with the user's key. Nothing rides on
 *   the demo's infrastructure.
 * - **Free demo** — no key: {@link FREE_AGENT_MODEL}, a $0/token model served
 *   through this deployment's `/api/gateway` proxy (`api/gateway/[path].ts`),
 *   which holds the Vercel AI Gateway credential server-side and refuses
 *   every other model. The `apiKey` passed to `createGateway` is a knowingly
 *   public placeholder the proxy replaces — it exists only because the
 *   provider requires one.
 */

/** Direct-API Anthropic model the agent runs on with the user's own key. */
export const AGENT_MODEL = "claude-sonnet-5"

/** The $0/token model the public demo serves through /api/gateway. */
export const FREE_AGENT_MODEL = "poolside/laguna-s-2.1-free"

/** Model id the given mode runs on — for badges and titles. */
export const agentModelId = (ownKey: boolean): string =>
  ownKey ? AGENT_MODEL : FREE_AGENT_MODEL

/** Build the language model for one agent run. */
export const createAgentModel = (ownKey: boolean) =>
  ownKey
    ? createAnthropic({
        apiKey: getApiKey("anthropic").value,
        headers: ANTHROPIC_BROWSER_HEADERS,
        fetch: boundFetch,
      })(AGENT_MODEL)
    : createGateway({
        baseURL: `${window.location.origin}/api/gateway`,
        // Replaced by the proxy's real credential server-side; a non-empty
        // value is required or the provider tries (and fails) to resolve an
        // OIDC token in the browser.
        apiKey: "corpora-free-demo",
        fetch: boundFetch,
      })(FREE_AGENT_MODEL)
