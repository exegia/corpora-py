import { atom } from "jotai"
import type { BridgeStatus } from "./types"

export const statusAtom = atom<BridgeStatus>("idle")
