export const SOCKET_URL = "ws://localhost:3000";

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
