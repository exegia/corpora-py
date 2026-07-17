import { cn } from "~/lib/utils"

/**
 * The Hugging Face brand mark (the full-color SVG served from /public),
 * used wherever the Hub surfaces in the UI -- the publish action on
 * /corpus/convert and the explore view -- so the destination is
 * recognizable at a glance. Size it with Tailwind classes (`size-4`, …),
 * like a lucide icon.
 */
export function HuggingFaceIcon({ className }: { className?: string }) {
  return (
    <img
      src="/hugging-face-icon.svg"
      alt=""
      aria-hidden="true"
      className={cn("shrink-0", className)}
    />
  )
}
