import { SOCKET_URL, type BridgeListener, type BridgeMessage, type BridgeStatus } from "@/types/socket";

const createId = () =>
	typeof crypto !== "undefined" && "randomUUID" in crypto
		? crypto.randomUUID()
		: `${Date.now()}-${Math.random().toString(16).slice(2)}`;

type PendingRequest = {
	resolve: (value: unknown) => void;
	reject: (error: Error) => void;
	timeout: ReturnType<typeof setTimeout>;
};

class SocketBridge {
	private ws?: WebSocket;
	private connectPromise?: Promise<void>;
	private readonly pending = new Map<string, PendingRequest>();
	private readonly handlers = new Map<string, (params: unknown) => unknown | Promise<unknown>>();
	private readonly listeners = new Map<string, Set<BridgeListener>>();
	private readonly sendQueue: BridgeMessage[] = [];
	status: BridgeStatus = "idle";

	async connect(): Promise<void> {
		if (this.ws?.readyState === WebSocket.OPEN) return;
		if (this.connectPromise) return this.connectPromise;

		this.setStatus("connecting");
		this.connectPromise = new Promise((resolve, reject) => {
			if (typeof window === "undefined") {
				reject(new Error("Websocket bridge is only available in the browser"));
				return;
			}

			const ws = new WebSocket(SOCKET_URL);
			this.ws = ws;

			ws.addEventListener("open", () => {
				this.setStatus("open");
				this.connectPromise = undefined;
				this.syncRegisteredMethods();
				this.flushQueue();
				resolve();
			});

			ws.addEventListener("message", async (event) => {
				await this.handleMessage(event.data);
			});

			ws.addEventListener("close", () => {
				this.ws = undefined;
				this.connectPromise = undefined;
				this.setStatus("closed");
				this.rejectPending(new Error("Websocket bridge closed"));
			});

			ws.addEventListener("error", () => {
				this.ws = undefined;
				this.connectPromise = undefined;
				this.setStatus("error");
				reject(new Error(`Could not connect to websocket bridge at ${SOCKET_URL}`));
			});
		});

		return this.connectPromise;
	}

	disconnect(): void {
		this.ws?.close();
		this.ws = undefined;
		this.setStatus("closed");
	}

	async callPython(method: string, params: unknown = {}): Promise<unknown> {
		return this.request({ type: "python.call", method, params });
	}

	async emit(event: string, payload: unknown): Promise<unknown> {
		return this.request({ type: "event.emit", event, payload });
	}

	register(method: string, handler: (params: unknown) => unknown | Promise<unknown>): () => void {
		this.handlers.set(method, handler);
		this.syncRegisteredMethods();

		return () => {
			this.handlers.delete(method);
			this.syncRegisteredMethods();
		};
	}

	on(type: string, listener: BridgeListener): () => void {
		const listeners = this.listeners.get(type) ?? new Set<BridgeListener>();
		listeners.add(listener);
		this.listeners.set(type, listeners);

		return () => {
			listeners.delete(listener);
			if (listeners.size === 0) this.listeners.delete(type);
		};
	}

	private async request(message: BridgeMessage, timeoutMs = 30_000): Promise<unknown> {
		await this.connect();

		const id = message.id ?? createId();
		const request = { ...message, id };

		return new Promise((resolve, reject) => {
			const timeout = setTimeout(() => {
				this.pending.delete(id);
				reject(new Error(`Timed out waiting for bridge response: ${message.type ?? message.method ?? "request"}`));
			}, timeoutMs);

			this.pending.set(id, { resolve, reject, timeout });
			this.send(request);
		});
	}

	private async handleMessage(raw: string | Blob | ArrayBuffer): Promise<void> {
		let message: BridgeMessage;

		try {
			const text =
				typeof raw === "string"
					? raw
					: raw instanceof Blob
						? await raw.text()
						: new TextDecoder().decode(raw);
			message = JSON.parse(text) as BridgeMessage;
		} catch (error) {
			this.notify({ type: "error", error: `invalid_bridge_message: ${String(error)}` });
			return;
		}

		if (message.type === "response" || message.type === "error") {
			this.resolvePending(message);
			return;
		}

		if (message.type === "client.call") {
			await this.handleClientCall(message);
			return;
		}

		this.notify(message);
	}

	private async handleClientCall(message: BridgeMessage): Promise<void> {
		const id = typeof message.id === "string" ? message.id : "";
		const method = typeof message.method === "string" ? message.method : "";

		if (!id || !method) return;

		const handler = this.handlers.get(method);
		if (!handler) {
			this.send({ type: "client.response", id, error: `No app handler registered for method: ${method}` });
			return;
		}

		try {
			const result = await handler(message.params);
			this.send({ type: "client.response", id, result });
		} catch (error) {
			this.send({ type: "client.response", id, error: String(error) });
		}
	}

	private resolvePending(message: BridgeMessage): void {
		if (!message.id) return;
		const pending = this.pending.get(message.id);
		if (!pending) return;

		clearTimeout(pending.timeout);
		this.pending.delete(message.id);

		if (message.error) {
			pending.reject(new Error(message.error));
			return;
		}

		pending.resolve(message.result);
	}

	private syncRegisteredMethods(): void {
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.send({ type: "client.register", methods: Array.from(this.handlers.keys()) });
		}
	}

	private send(message: BridgeMessage): void {
		if (this.ws?.readyState !== WebSocket.OPEN) {
			this.sendQueue.push(message);
			return;
		}

		this.ws.send(JSON.stringify(message));
	}

	private flushQueue(): void {
		while (this.sendQueue.length > 0 && this.ws?.readyState === WebSocket.OPEN) {
			const message = this.sendQueue.shift();
			if (message) this.ws.send(JSON.stringify(message));
		}
	}

	private rejectPending(error: Error): void {
		for (const pending of this.pending.values()) {
			clearTimeout(pending.timeout);
			pending.reject(error);
		}
		this.pending.clear();
	}

	private setStatus(status: BridgeStatus): void {
		this.status = status;
		this.notify({ type: "status", status });
	}

	private notify(message: BridgeMessage): void {
		for (const listener of this.listeners.get(message.type ?? "message") ?? []) {
			listener(message);
		}

		for (const listener of this.listeners.get("message") ?? []) {
			listener(message);
		}
	}
}

export const socketBridge = new SocketBridge();
export type { BridgeMessage, BridgeStatus };
