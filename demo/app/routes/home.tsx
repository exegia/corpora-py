import { Button, Card, Surface, Typography } from "@heroui/react";
import { Icon } from "@iconify/react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { socketBridge, type BridgeStatus } from "../socket";

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

    // return () => {
    //   offStatus();
    //   offPythonEvent();
    //   unregisterEcho();
    // };
  }, []);


  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6">
      <Surface
        className="rounded-2xl border-2 border-neutral-100 p-6 dark:border-neutral-800"
        variant="default"
      >
        <Typography type="h2">Login</Typography>
        <div className="mt-4 flex flex-col gap-3">
          <Button className="w-full" variant="tertiary">
            <Icon icon="devicon:google" />
            Sign in with Google
          </Button>
          <Button className="w-full" variant="tertiary">
            <Icon icon="ion:logo-apple" />
            Sign in with Apple.
          </Button>
        </div>
      </Surface>

      <Card variant="transparent">
        <Card.Header>
          <Card.Title>Get started</Card.Title>
          <Card.Description>
            Upload an existing corpus or convert a source document.
          </Card.Description>
        </Card.Header>
        <Card.Footer className="flex gap-2">
          <Button variant="primary" onPress={() => navigate("/corpus/upload")}>
            Upload corpus
          </Button>
          <Button variant="secondary" onPress={() => navigate("/corpus/convert")}>
            Convert source
          </Button>
        </Card.Footer>
      </Card>
    </div>
  );
}
