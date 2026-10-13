// The ElectroBun bridge (Bun main process <-> browser), see
// demo/src/bun/websocket.ts. Talks to a spawned Python subprocess over a
// separate JSON-RPC-over-stdio protocol (demo/src/bun/python-bridge.ts) --
// unrelated to the corpora-api server below.
export const SOCKET_URL = "ws://localhost:3000";

// The corpora-api FastAPI server (src/corpora_py/app.py) -- MCP at /mcp,
// document conversion at /convert. Overridable via VITE_API_URL for
// deployments where it doesn't run on localhost:8000 (see README.md).
export const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export type BridgeStatus = "idle" | "connecting" | "open" | "closed" | "error";
export type BridgeHandler = (params: unknown) => unknown | Promise<unknown>;
export type BridgeListener = (message: BridgeMessage) => void;

export type BridgeMessage = Record<string, unknown> & {
  id?: string;
  type?: string;
  method?: string;
  methods?: string[];
  params?: unknown;
  result?: unknown;
  error?: string;
  event?: string;
  payload?: unknown;
};

export type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timeout: ReturnType<typeof setTimeout>;
};
