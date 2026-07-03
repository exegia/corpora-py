import { atomWithImmer } from "jotai-immer"

const uploadAtom = atomWithImmer({
  key: "uploadAtom",
  progress: 0,
  isUploading: false,
  default: {
    file: null,
    status: "idle", // 'idle' | 'uploading' | 'success' | 'error'
    error: null
  }
})

export { uploadAtom }
