import { createMCPClient, type MCPClient } from "@ai-sdk/mcp"
import type { ToolSet } from "ai"
import {
  fetchIndex,
  fetchManifest,
  filenameToId,
  type CorpusIndex,
  type Manifest,
} from "~/lib/corpus-detail"
import { authHeaders, boundFetch } from "~/lib/settings"
import { API_URL } from "~/lib/types/socket"

/**
 * The chat route's corpus loader: turns a selected `.corpus` filename into
 * everything the chat needs — a connected MCP client, the `corpus_*` tools for
 * the agent, and the manifest + section index that seed the welcome message.
 *
 * The manifest/index fetches go through the typed REST client
 * (`lib/corpus-detail.ts`) rather than MCP tool calls so the data arrives as
 * JSON, but they hit the same backend archive layer the MCP tools use — the
 * first fetch is what pulls the archive down from the Hub into the server's
 * cache, which is why this step gets a progress UI (a big corpus takes a
 * moment on first load).
 */

export type LoadStepId = "connect" | "tools" | "manifest" | "index"

export const LOAD_STEPS: { id: LoadStepId; label: string }[] = [
  { id: "connect", label: "Connecting to the corpora MCP server" },
  { id: "tools", label: "Discovering corpus tools" },
  { id: "manifest", label: "Reading the corpus manifest" },
  { id: "index", label: "Indexing sections and node types" },
]

export type LoadedCorpus = {
  /** Full archive filename, e.g. "BHSA.corpus". */
  filename: string
  /** Route-style id (filename without ".corpus") — the display fallback. */
  id: string
  manifest: Manifest
  index: CorpusIndex
  /** Open MCP client — close it (via {@link closeCorpus}) when done. */
  client: MCPClient
  /** The `corpus_*` subset of the server's tools, handed to the agent. */
  tools: ToolSet
}

/** Display name for a loaded corpus: manifest name, else the filename stem. */
export const corpusDisplayName = (corpus: LoadedCorpus): string =>
  corpus.manifest.name?.trim() || corpus.id

/**
 * Load `filename` for chatting. `onStep` fires as each step *starts* (the
 * previous ones are implicitly done). Throws on failure with the MCP client
 * already closed.
 */
export const loadCorpus = async (
  filename: string,
  onStep: (step: LoadStepId) => void
): Promise<LoadedCorpus> => {
  const id = filenameToId(filename)

  onStep("connect")
  const client = await createMCPClient({
    transport: {
      type: "http",
      url: `${API_URL}/mcp/`,
      headers: authHeaders(),
      fetch: boundFetch,
    },
  })

  try {
    onStep("tools")
    const allTools = await client.tools()
    // Only the stored-archive tools: the runtime search tools operate on
    // CLI-loaded datasets, not the Hub archives this app displays.
    const tools = Object.fromEntries(
      Object.entries(allTools).filter(([name]) => name.startsWith("corpus_"))
    )
    if (Object.keys(tools).length === 0) {
      throw new Error(
        "The MCP server exposes no corpus_* tools. Is corpora-api running with Hub storage configured?"
      )
    }

    onStep("manifest")
    const manifest = await fetchManifest(id)

    onStep("index")
    const index = await fetchIndex(id)

    return { filename, id, manifest, index, client, tools }
  } catch (error) {
    void client.close().catch(() => {})
    throw error
  }
}

/** Fire-and-forget close of a loaded corpus's MCP client. */
export const closeCorpus = (corpus: LoadedCorpus): void => {
  void corpus.client.close().catch(() => {})
}
