import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { socketBridge, type BridgeStatus } from "../socket";
import { FileUploadProgressFill } from "@/components/upload";

export function meta() {
  return [{ title: "Corpora" }];
}

const formatResult = (value: unknown) => JSON.stringify(value, null, 2);

export default function Home() {
  const navigate = useNavigate();
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

    const connect = async () => {
      try {
        await socketBridge.connect();
      } catch (error) {
        setResult(String(error));
      }
    };

    void connect();

    return () => {
      offStatus();
      offPythonEvent();
      unregisterEcho();
    };
  }, []);


  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6">
      <FileUploadProgressFill />
    </div>
  );
}
