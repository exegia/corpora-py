import { Button, Card, Typography } from "@heroui/react";
import { useEffect, useState } from "react";
import { socketBridge, type BridgeStatus } from "../socket";

export function meta() {
  return [{ title: "Corpora" }];
}

const formatResult = (value: unknown) => JSON.stringify(value, null, 2);

export default function Logs() {
  const [status, setStatus] = useState<BridgeStatus>(socketBridge.status);
  const [result, setResult] = useState<string>("");
  const [events, setEvents] = useState<string[]>([]);

  useEffect(() => {
    const offStatus = socketBridge.on("status", (message) => {
      setStatus((message.status as BridgeStatus | undefined) ?? "idle");
    });

    const offPythonEvent = socketBridge.on("python.event", (message) => {
      setEvents((current) => [
        `${message.event ?? "python.event"}: ${formatResult(message.payload)}`,
        ...current,
      ].slice(0, 5));
    });

    const unregisterEcho = socketBridge.register("demo.echo", async (params) => ({
      ok: true,
      source: "demo.app",
      received: params,
    }));

    return () => {
      offStatus();
      offPythonEvent();
      unregisterEcho();
    };
  }, []);

  const callPython = async (method: string, params: unknown = {}) => {
    setResult("Loading…");
    try {
      const response = await socketBridge.callPython(method, params);
      setResult(formatResult(response));
    } catch (error) {
      setResult(String(error));
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6">
      <Card>
        <Card.Header>
          <Card.Title>Python bridge</Card.Title>
          <Card.Description>
            Call any Python method path from the demo app, and let Python call
            registered app handlers back through the websocket.
          </Card.Description>
        </Card.Header>
        <Card.Content className="flex flex-col gap-3">
          <Typography type="body">Socket status: {status}</Typography>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onPress={() => callPython("corpora_py.bridge.ping", { message: "hello from React" })}
            >
              Ping Python
            </Button>
            <Button
              variant="secondary"
              onPress={() => callPython("shared.auth.main")}
            >
              Auth demo
            </Button>
            <Button
              variant="secondary"
              onPress={() => callPython("corpora_py.bridge.emit", {
                event: "corpora.demo",
                payload: { message: "hello from Python" },
              })}
            >
              Python event
            </Button>
            <Button
              variant="secondary"
              onPress={() => callPython("corpora_py.bridge.call_client", {
                method: "demo.echo",
                params: { message: "hello from Python" },
              })}
            >
              Python → app
            </Button>
          </div>
          {result && (
            <pre className="max-h-64 text-neutral-800 dark:text-white  overflow-auto rounded-lg bg-neutral-100 p-3 text-xs dark:bg-neutral-900">
              {result}
            </pre>
          )}
          {events.length > 0 && (
            <div className="flex flex-col gap-1">
              <Typography type="h6">Recent Python events</Typography>
              {events.map((event, index) => (
                <code key={`${event}-${index}`} className="text-xs text-white">
                  {event}
                </code>
              ))}
            </div>
          )}
        </Card.Content>
      </Card>
    </div>
  );
}
