import { spawn, type Subprocess } from "bun"
import { existsSync } from "node:fs"

export type PythonCallParams = Record<string, unknown> | unknown[] | unknown | null;

export type PythonBridgeEvent = {
  event: string;
  payload?: unknown;
};

export type PythonClientCall = {
  id: string;
  method: string;
  params?: unknown;
  timeoutMs?: number;
};

type ProtocolMessage = Record<string, unknown> & {
  id?: string;
  type?: string;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: string;
  event?: string;
  payload?: unknown;
};

type PythonBridgeOptions = {
  onEvent?: (event: PythonBridgeEvent) => void | Promise<void>;
  onClientCall?: (request: PythonClientCall) => unknown | Promise<unknown>;
};

type StreamReader = {
  read: () => Promise<{ value?: string | Uint8Array; done: boolean }>;
};

export class PythonBridge {
  private pythonBin?: string
  private pythonHome = ""
  private proc: Subprocess | null = null
  private reader: StreamReader | null = null
  private buffer = ""
  private decoder = new TextDecoder()
  private initPromise: Promise<void> | null = null
  private callQueue: Promise<void> = Promise.resolve()
  private requestIndex = 0
  private onEvent?: PythonBridgeOptions["onEvent"]
  private onClientCall?: PythonBridgeOptions["onClientCall"]

  constructor(options: PythonBridgeOptions = {}) {
    this.onEvent = options.onEvent
    this.onClientCall = options.onClientCall

    // Dev override (used by Docker + SSH dev environments)
    // Set DEV_PYTHON_BIN (and optionally DEV_PYTHON_HOME) to use a system / venv Python
    // that has the local shared/client/admin workspaces (from corpora-py) available.
    const devPythonBin = process.env.DEV_PYTHON_BIN
    if (devPythonBin) {
      this.pythonBin = devPythonBin
      this.pythonHome = process.env.DEV_PYTHON_HOME || ""
    }
  }

  setEventHandler(handler?: PythonBridgeOptions["onEvent"]): void {
    this.onEvent = handler
  }

  setClientCallHandler(handler?: PythonBridgeOptions["onClientCall"]): void {
    this.onClientCall = handler
  }

  async init(): Promise<void> {
    if (this.proc && this.reader && this.proc.stdin) return
    if (this.initPromise) return this.initPromise

    this.initPromise = this.spawnPython()

    try {
      await this.initPromise
    } catch (error) {
      this.initPromise = null
      throw error
    }
  }

  async call<T = unknown>(method: string, params: PythonCallParams = {}): Promise<T> {
    await this.init()

    const previousCall = this.callQueue
    let releaseQueue: () => void = () => undefined
    this.callQueue = new Promise<void>((resolve) => {
      releaseQueue = resolve
    })

    await previousCall

    try {
      return await this.callUnlocked<T>(method, params)
    } finally {
      releaseQueue()
    }
  }

  async shutdown(): Promise<void> {
    await this.callQueue


    if (this.proc && this.proc.stdin && typeof this.proc.stdin === "object" && "end" in this.proc.stdin) {
      this.proc.stdin.end()
      await this.proc.exited
    }

    this.proc = null
    this.reader = null
    this.buffer = ""
    this.initPromise = null
  }

  private async spawnPython(): Promise<void> {
    await this.resolvePythonRuntime()

    if (!this.pythonBin) {
      throw new Error("Python binary could not be resolved")
    }

    const spawnEnv: Record<string, string | undefined> = { ...process.env }
    if (this.pythonHome) {
      spawnEnv.PYTHONHOME = this.pythonHome
      spawnEnv.PYTHONNOUSERSITE = "1"
    }

    this.proc = spawn([this.pythonBin, "-u", "-c", SUBPROCESS_SCRIPT], {
      stdin: "pipe",
      stdout: "pipe",
      stderr: "inherit",
      env: spawnEnv
    })

    if (!this.proc || !this.proc.stdout) {
      throw new Error("Failed to spawn Python subprocess")
    }

    const stdout = this.proc.stdout
    if (typeof stdout === "object" && "getReader" in stdout) {
      this.reader = stdout.getReader() as StreamReader
      return
    }

    throw new Error("Python subprocess stdout is not readable")
  }

  private async resolvePythonRuntime(): Promise<void> {
    if (this.pythonBin) return

    const { PATHS } = await import("electrobun/bun")
    const base = PATHS.RESOURCES_FOLDER
    // ElectroBun copy rules place non-Vite assets under an "app/" subfolder in
    // Contents/Resources (see electrobun.config.ts "resources/python": "python").
    // We probe the two most likely locations so it works across layout tweaks.
    const candidates = [
      `${base}/app/python`,
      `${base}/python`
    ]
    const chosen = candidates.find((p) => existsSync(`${p}/bin/python3`)) || candidates[0]
    this.pythonHome = chosen
    this.pythonBin = `${this.pythonHome}/bin/python3`

    if (!existsSync(`${this.pythonHome}/bin/python3`)) {
      console.warn(`[PythonBridge] Warning: python3 not found at ${this.pythonBin}. ` +
        `Make sure the runtime was built (uv run python -m scripts.build.embedded) and ` +
        `that start.py (or a clean electrobun build) copied it.`)
    }
  }

  private async callUnlocked<T>(method: string, params: PythonCallParams): Promise<T> {
    const id = `py-${++this.requestIndex}`
    this.writeProtocol({ id, method, params })

    while (true) {
      const response = await this.readProtocol()

      if (response.type === "event") {
        await this.handlePythonEvent(response)
        continue
      }

      if (response.type === "client.call") {
        await this.handlePythonClientCall(response)
        continue
      }

      if (response.id !== id) {
        console.warn("[PythonBridge] Ignoring unmatched Python protocol response", response)
        continue
      }

      if (response.error) {
        throw new Error(String(response.error))
      }

      return response.result as T
    }
  }

  private async handlePythonEvent(message: ProtocolMessage): Promise<void> {
    const event = typeof message.event === "string" ? message.event : "python.event"
    await this.onEvent?.({ event, payload: message.payload })
  }

  private async handlePythonClientCall(message: ProtocolMessage): Promise<void> {
    const id = typeof message.id === "string" ? message.id : `client-${Date.now()}`
    const method = typeof message.method === "string" ? message.method : ""

    try {
      if (!method) throw new Error("Python client call is missing a method")
      if (!this.onClientCall) throw new Error("No app client call handler is registered")

      const result = await this.onClientCall({
        id,
        method,
        params: message.params,
        timeoutMs: typeof message.timeoutMs === "number" ? message.timeoutMs : undefined
      })
      this.writeProtocol({ type: "client.response", id, result })
    } catch (error) {
      this.writeProtocol({ type: "client.response", id, error: String(error) })
    }
  }

  private async readProtocol(): Promise<ProtocolMessage> {
    if (!this.reader) throw new Error("Python subprocess is not initialized")

    while (true) {
      const newline = this.buffer.indexOf("\n")
      if (newline !== -1) {
        const line = this.buffer.slice(0, newline)
        this.buffer = this.buffer.slice(newline + 1)

        if (!line.trim()) continue

        try {
          return JSON.parse(line) as ProtocolMessage
        } catch (error) {
          console.warn("[PythonBridge] Ignoring non-JSON Python protocol line", line, error)
          continue
        }
      }

      const { value, done } = await this.reader.read()
      if (done) throw new Error("Python process exited unexpectedly")

      if (typeof value === "string") {
        this.buffer += value
      } else {
        this.buffer += this.decoder.decode(value)
      }
    }
  }

  private writeProtocol(message: ProtocolMessage): void {
    if (!this.proc || !this.proc.stdin || typeof this.proc.stdin === "number") {
      throw new Error("Python subprocess not initialized. Call init() first.")
    }

    this.proc.stdin.write(JSON.stringify(message) + "\n")
    this.proc.stdin.flush()
  }
}

const SUBPROCESS_SCRIPT = String.raw`
import asyncio
import contextlib
import dataclasses
import importlib
import inspect
import json
import sys
import time
import traceback
import types
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

_PROTOCOL_STDOUT = sys.stdout


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Enum):
        return to_jsonable(value.value)

    if isinstance(value, Path):
        return str(value)

    if dataclasses.is_dataclass(value):
        return to_jsonable(dataclasses.asdict(value))

    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]

    if hasattr(value, "model_dump"):
        try:
            return to_jsonable(value.model_dump(mode="json"))
        except TypeError:
            return to_jsonable(value.model_dump())
        except Exception:
            pass

    if hasattr(value, "dict"):
        try:
            return to_jsonable(value.dict())
        except Exception:
            pass

    if hasattr(value, "__dict__"):
        try:
            return {
                key: to_jsonable(val)
                for key, val in vars(value).items()
                if not key.startswith("_")
            }
        except Exception:
            pass

    return str(value)


def protocol_write(message: dict[str, Any]) -> None:
    _PROTOCOL_STDOUT.write(json.dumps(to_jsonable(message), ensure_ascii=False) + "\n")
    _PROTOCOL_STDOUT.flush()


def emit(event: str, payload: Any = None) -> None:
    protocol_write({"type": "event", "event": event, "payload": payload})


def call_client(method: str, params: Any = None, timeout: float = 30.0) -> Any:
    request_id = f"client-{uuid.uuid4()}"
    protocol_write({
        "type": "client.call",
        "id": request_id,
        "method": method,
        "params": {} if params is None else params,
        "timeoutMs": int(timeout * 1000),
    })

    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out waiting for app client method: {method}")

        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("Bridge input closed while waiting for app client response")

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        if message.get("type") != "client.response" or message.get("id") != request_id:
            continue

        if message.get("error"):
            raise RuntimeError(str(message["error"]))

        return message.get("result")


bridge_module = types.ModuleType("demo_bridge")
bridge_module.emit = emit
bridge_module.call_client = call_client
sys.modules["demo_bridge"] = bridge_module
sys.modules["corpora_py_demo_bridge"] = bridge_module


def resolve_callable(method_path: str):
    parts = method_path.split(".")
    if len(parts) < 2:
        raise ValueError(f"method must be a dotted Python path, got: {method_path}")

    last_error: Exception | None = None
    for index in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:index])
        try:
            target = importlib.import_module(module_name)
        except ImportError as exc:
            # Keep searching only when the candidate module itself does not exist.
            # If an existing module raises ImportError internally, surface that error.
            if exc.name != module_name:
                raise
            last_error = exc
            continue

        for attr in parts[index:]:
            target = getattr(target, attr)

        if not callable(target):
            raise TypeError(f"Resolved path is not callable: {method_path}")

        return target

    raise ValueError(f"Could not resolve Python callable: {method_path}") from last_error


def call_callable(fn, params: Any) -> Any:
    if params is None:
        result = fn()
    elif isinstance(params, list):
        result = fn(*params)
    elif isinstance(params, dict) and set(params.keys()).issubset({"args", "kwargs"}) and (
        "args" in params or "kwargs" in params
    ):
        result = fn(*params.get("args", []), **params.get("kwargs", {}))
    elif isinstance(params, dict):
        result = fn(**params)
    else:
        result = fn(params)

    if inspect.isawaitable(result):
        return asyncio.run(result)

    return result


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    request_id = None
    try:
        request = json.loads(line)
        request_id = request.get("id")
        method = request["method"]
        params = request.get("params", {})

        # Keep arbitrary Python prints from corrupting the JSON protocol.
        with contextlib.redirect_stdout(sys.stderr):
            fn = resolve_callable(method)
            result = call_callable(fn, params)

        response = {"id": request_id, "result": result}
    except Exception as exc:
        response = {
            "id": request_id,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }

    protocol_write(response)
`
