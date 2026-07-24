/**
 * Free-tier AI Gateway proxy for the public demo's chat.
 *
 * The chat agent runs entirely in the visitor's browser (see
 * `app/components/chat/chat-view.tsx`); when the visitor has no Anthropic key
 * of their own, its model calls come here instead, and this function forwards
 * them to the Vercel AI Gateway with the DEPLOYMENT's credential — which must
 * never reach the browser. Two hard rules keep this safe to expose publicly:
 *
 * - Only the models in `ALLOWED_MODELS` (free, $0/token) pass through. The
 *   gateway provider transmits the model id in the `ai-language-model-id`
 *   header, so the check needs no body parsing — anything else is refused
 *   before any upstream call, and the deployment's credential can't be
 *   ridden to paid models.
 * - Only the two endpoints the browser-side `@ai-sdk/gateway` provider
 *   actually uses are reachable (`language-model`, `config`) — this is not a
 *   general gateway proxy.
 *
 * Auth resolution mirrors `@ai-sdk/gateway`: an explicit AI_GATEWAY_API_KEY
 * env var wins, otherwise the deployment's OIDC token (auto-provisioned on
 * Vercel; `vercel env pull` writes one to .env.local for `vercel dev`). Local
 * `bun run vite:dev` doesn't run this function at all — vite.config.ts
 * proxies /api/gateway to the real gateway with the same env fallback.
 */

const GATEWAY_BASE = "https://ai-gateway.vercel.sh/v4/ai"

export const ALLOWED_MODELS = new Set(["poolside/laguna-s-2.1-free"])

const ALLOWED = new Map([
  ["language-model", "POST"],
  ["config", "GET"],
])

export default async function handler(request: Request): Promise<Response> {
  // Base required: Vercel's Node runtime hands web handlers a RELATIVE
  // `request.url` (e.g. "/api/gateway/language-model?path=…"), which a
  // bare `new URL(...)` rejects with ERR_INVALID_URL.
  const segments = new URL(request.url, "http://gateway.internal").pathname
    .split("/")
    .filter(Boolean)
  const path = segments[segments.length - 1] ?? ""

  if (ALLOWED.get(path) !== request.method) {
    return Response.json(
      { error: `Unsupported gateway route: ${request.method} ${path}` },
      { status: 404 }
    )
  }

  const modelId = request.headers.get("ai-language-model-id")
  if (path === "language-model" && (!modelId || !ALLOWED_MODELS.has(modelId))) {
    return Response.json(
      {
        error: `This demo only serves the free model(s): ${[...ALLOWED_MODELS].join(", ")}. Bring your own Anthropic key in Settings for anything else.`,
      },
      { status: 403 }
    )
  }

  const token =
    process.env.AI_GATEWAY_API_KEY ?? process.env.VERCEL_OIDC_TOKEN
  if (!token) {
    return Response.json(
      { error: "AI Gateway credential is not configured on this deployment." },
      { status: 503 }
    )
  }

  // Forward only the gateway-protocol headers plus content-type; the
  // browser's own authorization header (a dummy value, see chat-view.tsx) is
  // deliberately replaced with the deployment credential.
  const headers = new Headers()
  for (const [name, value] of request.headers) {
    if (name.startsWith("ai-") || name === "content-type") {
      headers.set(name, value)
    }
  }
  headers.set("authorization", `Bearer ${token}`)

  const upstream = await fetch(`${GATEWAY_BASE}/${path}`, {
    method: request.method,
    headers,
    body: request.body,
    // Required by Node's fetch to stream a request body.
    ...(request.body ? { duplex: "half" as const } : {}),
  })

  return new Response(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  })
}
