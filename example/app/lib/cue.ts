import { bind, play, setEnabled, type SoundName } from "cuelume"

/**
 * Interaction sounds for the convert flow, powered by `cuelume` -- a
 * dependency-free Web Audio library that synthesizes every cue live (no audio
 * files to ship or preload).
 *
 * Two layers work together:
 *
 * - **Declarative clicks.** Buttons in the convert flow carry
 *   `data-cuelume-press` / `data-cuelume-release` attributes; a single
 *   `bindCues()` call (from the app root) delegates the pointer listeners for
 *   the whole document. Press/release are mouse-only by design in cuelume,
 *   which suits this Electrobun desktop app.
 * - **Imperative lifecycle cues.** The moments that aren't a plain click --
 *   a file being accepted, a conversion finishing, an archive saved, a
 *   failure -- are played with `cue(...)` below.
 *
 * Keeping the semantic-event → sound mapping in one table (`CUES`) makes the
 * sound design easy to see and tweak without hunting through components.
 */
const CUES = {
  /** A source file was accepted and its upload/conversion began. */
  upload: "chime",
  /** A dropped or picked file was rejected before upload (wrong type, etc.). */
  reject: "droplet",
  /** Conversion finished and the `.corpus` archive is ready to save. */
  converted: "success",
  /** The finished archive was written to disk. */
  saved: "sparkle",
  /** Conversion failed. */
  error: "droplet",
  /** The GitHub repo URL validated — the repository exists and can be imported. */
  repoValid: "bloom",
  /** GitHub repo validation failed, or the repo import itself failed. */
  repoInvalid: "droplet"
} satisfies Record<string, SoundName>

export type Cue = keyof typeof CUES

/**
 * Plays the cue for a named convert-flow event. A no-op during SSR and when
 * Web Audio is unavailable -- `cuelume` guards both internally.
 */
export const cue = (name: Cue): void => play(CUES[name])

/** Enables or disables all cues (both declarative clicks and imperative). */
export const setCuesEnabled = (enabled: boolean): void => setEnabled(enabled)

/**
 * Activates declarative `data-cuelume-*` cues for the whole document.
 * Idempotent and SSR-safe -- call once from a client-side mount effect.
 */
export const bindCues = (): void => bind()
