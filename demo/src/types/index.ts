import { BrowserWindow } from "electrobun";


type State = {
  activeWindow: BrowserWindow
  windows: number[]
  theme: "dark" | "light"
};

export type { State as WindowState }
