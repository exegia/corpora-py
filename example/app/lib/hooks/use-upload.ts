import { useAtomValue } from "jotai"
import { useEffect } from "react"
import { uploadAtom } from "~/lib/atoms/upload-atom"
import {
  deleteUpload,
  initUploadManager,
  retryUpload,
  saveUpload,
  uploadFile
} from "~/lib/uploads/manager"

export type { UploadOptions } from "~/lib/uploads/manager"

/**
 * React view over the upload/conversion manager (`~/lib/uploads/manager`).
 *
 * The heavy lifting -- POSTing to `/convert`, per-job WebSocket tracking,
 * blob caching, save-to-disk, localStorage history -- lives at module level
 * in the manager, not in this hook, so any number of components can mount
 * this without duplicating subscriptions, and jobs keep being tracked after
 * the component that started them unmounts. The returned functions are the
 * manager's own module-level exports: referentially stable forever, safe to
 * pass straight into effect deps or memoized children.
 */
export const useUpload = () => {
  const uploads = useAtomValue(uploadAtom)

  // Idempotent; runs client-side only (never during SSR/prerender). First
  // mount anywhere in the app hydrates history and resumes job tracking.
  useEffect(initUploadManager, [])

  return { uploads, uploadFile, deleteUpload, retryUpload, saveUpload }
}

export default useUpload
