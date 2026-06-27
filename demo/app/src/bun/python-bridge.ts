import { PATHS } from "electrobun/bun";
import { spawn, type Subprocess } from "bun";

export class PythonBridge {
  private pythonBin: string;
  private pythonHome: string;
  private proc: Subprocess | null = null;
  private reader: ReadableStreamDefaultReader | null = null;
  private buffer = "";
  private decoder = new TextDecoder();

  constructor() {
    // Dev override (used by Docker + SSH dev environments)
    // Set DEV_PYTHON_BIN (and optionally DEV_PYTHON_HOME) to use a system / venv Python
    // that has the local exegia/corpora-py package available.
    const devPythonBin = process.env.DEV_PYTHON_BIN;
    if (devPythonBin) {
      this.pythonBin = devPythonBin;
      this.pythonHome = process.env.DEV_PYTHON_HOME || "";
    } else {
      const base = PATHS.RESOURCES_FOLDER;
      this.pythonHome = `${base}/python`;
      this.pythonBin = `${this.pythonHome}/bin/python3`;
    }
  }

  async init(): Promise<void> {
      const spawnEnv: Record<string, string | undefined> = { ...process.env };
      if (this.pythonHome) {
        spawnEnv.PYTHONHOME = this.pythonHome;
        spawnEnv.PYTHONNOUSERSITE = "1";
      }
      this.proc = spawn([this.pythonBin, "-u", "-c", SUBPROCESS_SCRIPT], {
        stdin: "pipe",
        stdout: "pipe",
        stderr: "inherit",
        env: spawnEnv,
      });
      if (!this.proc || !this.proc.stdout) throw new Error("Failed to spawn Python subprocess");
      const stdout = this.proc.stdout;
      if (typeof stdout == "object" && 'getReader' in stdout) {
        this.reader = stdout.getReader();
      }
  }

  async call(method: string, params: Record<string, any> = {}): Promise<any> {
    if (!this.proc || !this.reader || !this.proc.stdin) {
          throw new Error("Not initialized. Call init() first.");
        }
        if (typeof this.proc.stdin == 'number') {
          throw new Error("Python subprocess not initialized. Call init() first.");
        }
        this.proc.stdin.write(JSON.stringify({ method, params }) + "\n");
        this.proc.stdin.flush();

        while (true) {
          const { value, done } = await this.reader.read();
          if (done) throw new Error("Python process exited unexpectedly");
          this.buffer += this.decoder.decode(value);
          const idx = this.buffer.indexOf("\n");
          if (idx !== -1) {
            const line = this.buffer.slice(0, idx);
            this.buffer = this.buffer.slice(idx + 1);
            const response = JSON.parse(line);
            if (response.error) throw new Error(response.error);
            return response.result;
          }
      }
  }

  async shutdown(): Promise<void> {
    if (this.proc && this.proc.stdin && typeof this.proc.stdin == 'object' && 'end' in this.proc.stdin) {
      this.proc.stdin.end();
      await this.proc.exited;
      this.proc = null;
      this.reader = null;
    }
  }
}

const SUBPROCESS_SCRIPT = `
import sys, json, importlib, traceback

def resolve_callable(method_path):
    parts = method_path.rsplit(".", 1)
    if len(parts) == 2:
        module = importlib.import_module(parts[0])
        return getattr(module, parts[1])
    else:
        raise ValueError(f"method must be 'module.function', got: {method_path}")

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        request = json.loads(line)
        method = request["method"]
        params = request.get("params", {})
        fn = resolve_callable(method)
        result = fn(**params)
        try:
            json.dumps(result)
        except (TypeError, ValueError):
            result = str(result)
        response = {"result": result}
    except Exception as e:
        response = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
    sys.stdout.write(json.dumps(response) + "\\n")
    sys.stdout.flush()
`;
