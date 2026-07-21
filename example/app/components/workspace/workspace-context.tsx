import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"

import type { CorpusReference } from "./types"

/**
 * Shared state wiring the corpus reader (left pane) to the chat panel (right
 * pane): a DOM registry so chat reference chips can scroll/focus the original
 * passage block, the selected block, pending composer inserts, structured
 * attachments, the chat open/collapsed flag, and a polite live region for
 * status feedback ("Copied…", "Attached…").
 */

type PendingInsert = { text: string; nonce: number }

type WorkspaceContextValue = {
  corpusId: string
  /** Registry key of the currently selected block, if any. */
  selectedKey: string | null
  setSelectedKey: (key: string | null) => void
  /** Register a rendered block's element; returns the unregister cleanup. */
  registerBlock: (key: string, element: HTMLElement) => () => void
  /** Scroll to + focus a block by key (falls back to matching `ref`). */
  focusBlock: (blockKey: string, ref?: string) => boolean
  attachments: CorpusReference[]
  attach: (reference: CorpusReference) => void
  removeAttachment: (id: string) => void
  clearAttachments: () => void
  /** Text queued for the chat composer; consumed by the chat panel. */
  pendingInsert: PendingInsert | null
  insertIntoComposer: (text: string) => void
  consumePendingInsert: () => void
  chatOpen: boolean
  setChatOpen: (open: boolean) => void
  /** Announce a message to assistive tech via the polite live region. */
  announce: (message: string) => void
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)

export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext)
  if (!context)
    throw new Error("useWorkspace must be used within a WorkspaceProvider")
  return context
}

export function WorkspaceProvider({
  corpusId,
  children,
}: {
  corpusId: string
  children: ReactNode
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<CorpusReference[]>([])
  const [pendingInsert, setPendingInsert] = useState<PendingInsert | null>(null)
  const [chatOpen, setChatOpen] = useState(true)
  const [announcement, setAnnouncement] = useState("")
  const blocksRef = useRef(new Map<string, HTMLElement>())

  const registerBlock = useCallback((key: string, element: HTMLElement) => {
    blocksRef.current.set(key, element)
    return () => {
      if (blocksRef.current.get(key) === element) blocksRef.current.delete(key)
    }
  }, [])

  const announce = useCallback((message: string) => {
    // Clear first so repeating the same message still re-announces.
    setAnnouncement("")
    window.setTimeout(() => setAnnouncement(message), 50)
  }, [])

  const focusBlock = useCallback(
    (blockKey: string, ref?: string) => {
      let foundKey = blocksRef.current.has(blockKey) ? blockKey : null
      if (!foundKey && ref) {
        // The exact block may have unmounted (pagination/reload); fall back to
        // the first rendered block sharing the same passage ref.
        for (const key of blocksRef.current.keys()) {
          if (key.startsWith(`${ref}#`)) {
            foundKey = key
            break
          }
        }
      }
      const element = foundKey ? blocksRef.current.get(foundKey) : undefined
      if (!foundKey || !element) {
        announce("That passage isn't loaded in the reader right now.")
        return false
      }
      setSelectedKey(foundKey)
      element.scrollIntoView({ block: "center", behavior: "smooth" })
      element.focus({ preventScroll: true })
      announce(`Focused passage ${ref ?? foundKey}`)
      return true
    },
    [announce]
  )

  const attach = useCallback(
    (reference: CorpusReference) => {
      setChatOpen(true)
      setAttachments((prev) => {
        if (prev.some((a) => a.blockKey === reference.blockKey)) {
          announce(`Passage ${reference.ref} is already attached`)
          return prev
        }
        announce(`Attached passage ${reference.ref} to the chat`)
        return [...prev, reference]
      })
    },
    [announce]
  )

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const clearAttachments = useCallback(() => setAttachments([]), [])

  const insertIntoComposer = useCallback((text: string) => {
    setChatOpen(true)
    setPendingInsert({ text, nonce: Date.now() })
  }, [])

  const consumePendingInsert = useCallback(() => setPendingInsert(null), [])

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      corpusId,
      selectedKey,
      setSelectedKey,
      registerBlock,
      focusBlock,
      attachments,
      attach,
      removeAttachment,
      clearAttachments,
      pendingInsert,
      insertIntoComposer,
      consumePendingInsert,
      chatOpen,
      setChatOpen,
      announce,
    }),
    [
      corpusId,
      selectedKey,
      registerBlock,
      focusBlock,
      attachments,
      attach,
      removeAttachment,
      clearAttachments,
      pendingInsert,
      insertIntoComposer,
      consumePendingInsert,
      chatOpen,
      announce,
    ]
  )

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </WorkspaceContext.Provider>
  )
}
