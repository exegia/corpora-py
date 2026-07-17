import { BrowserWindow } from "electrobun"

export * from "./socket"

export type WindowState = {
  activeWindow: BrowserWindow
  windows: number[]
  theme: "dark" | "light"
};
