import { atom } from "jotai";
import { BridgeStatus } from "../types";

export const statusAtom = atom<BridgeStatus>("idle")
