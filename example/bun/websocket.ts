import Bun, { type Server, type ServerWebSocket } from "bun"
import { PythonBridge } from "./python-bridge"

type SocketData = {
  clientId: string;
  methods: Set<string>;
};

type RpcMessage = Record<string, unknown> & {
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

type PendingClientCall = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timeout: ReturnType<typeof setTimeout>;
};

const textDecoder = new TextDecoder()

class Connect {
  public static shared: Connect = new Connect()

  private server?: Server<SocketData>
  private readonly clients = new Set<ServerWebSocket<SocketData>>()
  private readonly pendingClientCalls = new Map<string, PendingClientCall>()
  private readonly py: PythonBridge
  private pythonReady = false

  private constructor() {
    this.py = new PythonBridge({
      onEvent: async (event) => {
        this.broadcast({
          type: "python.event",
          event: event.event,
          payload: event.payload
        })
      },
      onClientCall: async (request) => this.callClient(request.method, request.params, request.timeoutMs)
    })
  }

  public start = async (): Promise<void> => {
    if (!this.server) this.server = this._start()
    if (!this.server) return

    const hostname = this.server.hostname
    const port = this.server.port
    const url = `${hostname}:${port}`
    console.log(`[WEBSOCKET]: host: ${url}`)
    this.broadcast({ type: "server.ready", url })

    try {
      await this.py.init()
      this.pythonReady = true
      console.log("[WEBSOCKET]: python bridge ready")
      this.broadcast({ type: "python.ready" })
    } catch (error) {
      this.pythonReady = false
      console.error("[WEBSOCKET]: python bridge init error", error)
      this.broadcast({ type: "python.error", error: String(error) })
    }
  }

  public close = async (): Promise<void> => {
    if (this.server) {
      this.server.stop()
      this.server = undefined
    }

    for (const pending of this.pendingClientCalls.values()) {
      clearTimeout(pending.timeout)
      pending.reject(new Error("Websocket bridge closed"))
    }
    this.pendingClientCalls.clear()
    this.clients.clear()

    try {
      await this.py.shutdown()
    } catch (error) {
      console.error("[WEBSOCKET]: python shutdown error", error)
    } finally {
      this.pythonReady = false
    }
  }

  private _start = (): Server<SocketData> => {
    console.log("[WEBSOCKET]: Socket Server starting...")
    const connect = this

    return Bun.serve<SocketData>({
      fetch(req, server) {
        const success = server.upgrade(req, {
          data: {
            clientId: crypto.randomUUID(),
            methods: new Set<string>()
          }
        })
        return success ? undefined : new Response("Websocket upgrade error", { status: 400 })
      },
      websocket: {
        open(ws) {
          connect.clients.add(ws)
          console.log(`[WEBSOCKET]: client connected ${ws.data.clientId}`)
          connect.send(ws, {
            type: "welcome",
            clientId: ws.data.clientId,
            pythonReady: connect.pythonReady
          })
        },
        async message(ws, message) {
          await connect.handleMessage(ws, message)
        },
        close(ws, code, reason) {
          connect.clients.delete(ws)
          console.log(`[WEBSOCKET]: client closed ${ws.data.clientId} code=${code} reason=${reason}`)
        }
      }
    })
  }

  private async handleMessage(
    ws: ServerWebSocket<SocketData>,
    rawMessage: string | ArrayBuffer | Uint8Array
  ): Promise<void> {
    let payload: RpcMessage

    try {
      payload = this.parseMessage(rawMessage)
    } catch (error) {
      this.send(ws, { type: "error", error: `invalid_message: ${String(error)}` })
      return
    }

    const type = payload.type ?? (payload.method ? "python.call" : undefined)

    try {
      switch (type) {
        case "ping": {
          this.send(ws, { type: "response", id: payload.id, result: "pong" })
          return
        }

        case "python.call": {
          await this.handlePythonCall(ws, payload)
          return
        }

        case "python.init": {
          await this.py.init()
          this.pythonReady = true
          this.send(ws, { type: "response", id: payload.id, result: "ok" })
          this.broadcast({ type: "python.ready" })
          return
        }

        case "python.shutdown": {
          await this.py.shutdown()
          this.pythonReady = false
          this.send(ws, { type: "response", id: payload.id, result: "ok" })
          this.broadcast({ type: "python.closed" })
          return
        }

        case "client.register": {
          this.registerClientMethods(ws, payload.methods)
          this.send(ws, {
            type: "response",
            id: payload.id,
            result: { methods: Array.from(ws.data.methods) }
          })
          return
        }

        case "client.response": {
          this.resolveClientCall(payload)
          return
        }

        case "event.emit": {
          const event = typeof payload.event === "string" ? payload.event : "app.event"
          this.broadcast({ type: "app.event", event, payload: payload.payload }, ws)
          this.send(ws, { type: "response", id: payload.id, result: "ok" })
          return
        }

        default: {
          this.send(ws, {
            type: "error",
            id: payload.id,
            error: `unsupported_message_type: ${String(type)}`
          })
        }
      }
    } catch (error) {
      console.error("[WEBSOCKET]: message handler error", error)
      this.send(ws, { type: "error", id: payload.id, error: String(error) })
    }
  }

  private async handlePythonCall(ws: ServerWebSocket<SocketData>, payload: RpcMessage): Promise<void> {
    if (!payload.method || typeof payload.method !== "string") {
      this.send(ws, { type: "error", id: payload.id, error: "missing_or_invalid_method" })
      return
    }

    const result = await this.py.call(payload.method, payload.params ?? {})
    this.pythonReady = true
    this.send(ws, { type: "response", id: payload.id, result })
  }

  private async callClient(method: string, params: unknown, timeoutMs = 30_000): Promise<unknown> {
    const registeredClients = Array.from(this.clients).filter((client) => client.data.methods.has(method))
    const targets = registeredClients.length > 0 ? registeredClients : Array.from(this.clients)

    if (targets.length === 0) {
      throw new Error(`No connected app clients are available for method: ${method}`)
    }

    const id = `client-${crypto.randomUUID()}`
    const payload: RpcMessage = { type: "client.call", id, method, params }

    const result = await new Promise<unknown>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingClientCalls.delete(id)
        reject(new Error(`Timed out waiting for app client method: ${method}`))
      }, timeoutMs)

      this.pendingClientCalls.set(id, { resolve, reject, timeout })
      for (const client of targets) this.send(client, payload)
    })

    return result
  }

  private resolveClientCall(payload: RpcMessage): void {
    if (!payload.id) return

    const pending = this.pendingClientCalls.get(payload.id)
    if (!pending) return

    clearTimeout(pending.timeout)
    this.pendingClientCalls.delete(payload.id)

    if (payload.error) {
      pending.reject(new Error(payload.error))
      return
    }

    pending.resolve(payload.result)
  }

  private registerClientMethods(ws: ServerWebSocket<SocketData>, methods: string[] | undefined): void {
    ws.data.methods = new Set((methods ?? []).filter((method) => typeof method === "string" && method.length > 0))
    console.log(`[WEBSOCKET]: client ${ws.data.clientId} registered methods`, Array.from(ws.data.methods))
  }

  private parseMessage(rawMessage: string | ArrayBuffer | Uint8Array): RpcMessage {
    const text = typeof rawMessage === "string"
      ? rawMessage
      : rawMessage instanceof ArrayBuffer
        ? textDecoder.decode(new Uint8Array(rawMessage))
        : textDecoder.decode(rawMessage)
    const trimmed = text.trim()

    if (trimmed === "ping") return { type: "ping" }

    const payload = JSON.parse(trimmed) as RpcMessage
    if (!payload || typeof payload !== "object") {
      throw new Error("payload must be a JSON object")
    }

    return payload
  }

  private broadcast(payload: RpcMessage, except?: ServerWebSocket<SocketData>): void {
    for (const client of this.clients) {
      if (client !== except) this.send(client, payload)
    }
  }

  private send(ws: ServerWebSocket<SocketData>, payload: RpcMessage): void {
    try {
      ws.send(JSON.stringify(payload))
    } catch (error) {
      console.error("[WEBSOCKET]: send error", error)
    }
  }
}

const connect = Connect.shared
export { connect }
