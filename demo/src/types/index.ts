import { BrowserWindow } from "electrobun";


type State = {
  activeWindow: BrowserWindow
  windows: number[]
  theme: "dark" | "light"
};

type SocketMessage = {
  id: string;
  payload: any;
}

export type { State as WindowState, SocketMessage }
