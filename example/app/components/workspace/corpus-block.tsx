import { useEffect, useRef, type KeyboardEvent, type MouseEvent } from "react"
import { Check, Copy, Paperclip, TextQuote } from "lucide-react"
import { Button } from "~/components/ui/button"
import { useClipboard } from "~/lib/hooks"
import type { Passage } from "~/lib/corpus-detail"
import { cn } from "~/lib/utils"

import { makeId } from "./types"
import { useWorkspace } from "./workspace-context"

/**
 * One selectable passage block in the reader. The ref label is a toggle button
 * (aria-pressed) for selection; the block also toggles on plain click and on
 * Enter/Space when focused. A hover/focus-revealed toolbar (always visible
 * below lg, where there's no hover) offers copy, insert-into-composer, and
 * attach-as-reference. The `<li>` is programmatically focusable (tabIndex -1)
 * so chat reference chips can scroll to and focus it.
 */
export function CorpusBlock({
  passage,
  blockKey,
}: {
  passage: Passage
  blockKey: string
}) {
  const {
    corpusId,
    selectedKey,
    setSelectedKey,
    registerBlock,
    attach,
    insertIntoComposer,
    announce,
  } = useWorkspace()
  const { copied, copy } = useClipboard()
  const itemRef = useRef<HTMLLIElement>(null)

  useEffect(() => {
    const element = itemRef.current
    if (!element) return
    return registerBlock(blockKey, element)
  }, [blockKey, registerBlock])

  const selected = selectedKey === blockKey
  const toggleSelect = () => {
    setSelectedKey(selected ? null : blockKey)
    announce(
      selected
        ? `Deselected passage ${passage.ref}`
        : `Selected passage ${passage.ref}`
    )
  }

  const onBlockClick = (event: MouseEvent<HTMLLIElement>) => {
    // Clicks on the toolbar / ref button handle themselves.
    if ((event.target as HTMLElement).closest("button")) return
    toggleSelect()
  }

  const onBlockKeyDown = (event: KeyboardEvent<HTMLLIElement>) => {
    if (event.target !== event.currentTarget) return
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      toggleSelect()
    }
  }

  const handleCopy = async () => {
    const result = await copy(`${passage.text}\n— ${passage.ref}`, blockKey)
    announce(
      result.success
        ? `Copied passage ${passage.ref} to the clipboard`
        : "Copy failed"
    )
  }

  const handleInsert = () => {
    insertIntoComposer(`“${passage.text.trim()}” — ${passage.ref}`)
    announce(`Inserted passage ${passage.ref} into the chat composer`)
  }

  const handleAttach = () => {
    attach({
      id: makeId(),
      corpusId,
      ref: passage.ref,
      blockKey,
      excerpt:
        passage.text.length > 140
          ? `${passage.text.slice(0, 140)}…`
          : passage.text,
    })
  }

  return (
    <li
      ref={itemRef}
      tabIndex={-1}
      onClick={onBlockClick}
      onKeyDown={onBlockKeyDown}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "group rounded-md border p-3 transition-colors outline-none",
        "hover:border-neutral-300 hover:bg-neutral-50 dark:hover:border-neutral-700 dark:hover:bg-neutral-900",
        "focus-within:border-neutral-300 focus:ring-2 focus:ring-ring/60 dark:focus-within:border-neutral-700",
        selected &&
          "border-amber-400 bg-amber-50/60 hover:border-amber-400 hover:bg-amber-50/80 dark:border-amber-500/60 dark:bg-amber-400/10 dark:hover:border-amber-500/60 dark:hover:bg-amber-400/15"
      )}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <button
          type="button"
          aria-pressed={selected}
          onClick={toggleSelect}
          className="cursor-pointer rounded font-mono text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60"
        >
          <span className="sr-only">
            {selected ? "Deselect" : "Select"} passage{" "}
          </span>
          {passage.ref}
        </button>

        <div
          role="group"
          aria-label={`Actions for passage ${passage.ref}`}
          className="flex items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 focus-within:opacity-100 max-lg:opacity-100"
        >
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Copy passage ${passage.ref}`}
            onClick={handleCopy}
            data-cuelume-press
            data-cuelume-release
          >
            {copied === blockKey ? (
              <Check className="text-success" aria-hidden="true" />
            ) : (
              <Copy aria-hidden="true" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Insert passage ${passage.ref} into the chat composer`}
            onClick={handleInsert}
            data-cuelume-press
            data-cuelume-release
          >
            <TextQuote aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Attach passage ${passage.ref} as a chat reference`}
            onClick={handleAttach}
            data-cuelume-press
            data-cuelume-release
          >
            <Paperclip aria-hidden="true" />
          </Button>
        </div>
      </div>

      <p className="text-sm whitespace-pre-wrap text-neutral-800 dark:text-neutral-200">
        {passage.text}
      </p>
    </li>
  )
}
