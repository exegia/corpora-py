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
 * env var wins, otherwise the deployment's OIDC token. Local
 * `bun run vite:dev` doesn't run this function at all — vite.config.ts
 * proxies /api/gateway to the real gateway with the same env fallback.
 *
 * Written against the CLASSIC Node signature (IncomingMessage/ServerResponse)
 * on purpose: Vercel's builder invoked the web-standard `(request: Request)`
 * shape with a Node request anyway (`request.url` relative,
 * `request.headers.get` undefined — FUNCTION_INVOCATION_FAILED in prod), so
 * this depends only on the invocation style that's actually delivered.
 */

import type { IncomingMessage, ServerResponse } from "node:http"
import { Readable, Writable } from "node:stream"

const GATEWAY_BASE = "https://ai-gateway.vercel.sh/v4/ai"

export const ALLOWED_MODELS = new Set(["poolside/laguna-s-2.1-free"])

const ALLOWED = new Map([
  ["language-model", "POST"],
  ["config", "GET"],
])

const sendJson = (
  res: ServerResponse,
  status: number,
  body: Record<string, string>
): void => {
  res.writeHead(status, { "content-type": "application/json" })
  res.end(JSON.stringify(body))
}

const headerValue = (
  req: IncomingMessage,
  name: string
): string | undefined => {
  const value = req.headers[name]
  return Array.isArray(value) ? value[0] : value
}

export default async function handler(
  req: IncomingMessage,
  res: ServerResponse
): Promise<void> {
  const pathname = (req.url ?? "").split("?")[0] ?? ""
  const segments = pathname.split("/").filter(Boolean)
  const path = segments[segments.length - 1] ?? ""

  if (ALLOWED.get(path) !== req.method) {
    sendJson(res, 404, {
      error: `Unsupported gateway route: ${req.method} ${path}`,
    })
    return
  }

  const modelId = headerValue(req, "ai-language-model-id")
  if (path === "language-model" && (!modelId || !ALLOWED_MODELS.has(modelId))) {
    sendJson(res, 403, {
      error: `This demo only serves the free model(s): ${[...ALLOWED_MODELS].join(", ")}. Bring your own Anthropic key in Settings for anything else.`,
    })
    return
  }

  const token =
    process.env.AI_GATEWAY_API_KEY ?? process.env.VERCEL_OIDC_TOKEN
  if (!token) {
    sendJson(res, 503, {
      error: "AI Gateway credential is not configured on this deployment.",
    })
    return
  }

  // Forward only the gateway-protocol headers plus content-type; the
  // browser's own authorization header (a dummy value, see chat-view.tsx) is
  // deliberately replaced with the deployment credential.
  const headers = new Headers()
  for (const [name, value] of Object.entries(req.headers)) {
    if (name.startsWith("ai-") || name === "content-type") {
      const single = Array.isArray(value) ? value[0] : value
      if (single !== undefined) headers.set(name, single)
    }
  }
  headers.set("authorization", `Bearer ${token}`)

  const upstream = await fetch(`${GATEWAY_BASE}/${path}`, {
    method: req.method,
    headers,
    ...(req.method === "POST"
      ? {
          body: Readable.toWeb(req) as ReadableStream,
          // Required by Node's fetch to stream a request body.
          duplex: "half" as const,
        }
      : {}),
  })

  // fetch already decompressed the body — the encoding/length headers of the
  // compressed wire form would corrupt the re-served response.
  const responseHeaders: Record<string, string> = {}
  for (const [name, value] of upstream.headers) {
    if (!["content-encoding", "content-length", "transfer-encoding"].includes(name)) {
      responseHeaders[name] = value
    }
  }
  res.writeHead(upstream.status, responseHeaders)

  if (upstream.body) {
    await upstream.body.pipeTo(Writable.toWeb(res))
  } else {
    res.end()
  }
}
