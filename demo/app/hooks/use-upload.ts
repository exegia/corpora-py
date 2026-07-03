import { useAtom } from "jotai"
import { useState } from "react"
import { uploadAtom } from "../atoms/upload-atom"

const useUpload = () => {
  const [uploadValue, setUploadValue] = useAtom(uploadAtom)

  const uploadFile = async (file: File) => {
    try {
      // Here you would typically make an API call to upload the file
      // Example: await api.uploadFile(file);
    } catch (err) {
    } finally {
      setUploading(false)
    }
  }

  return { uploading, progress, error, uploadFile }
}

export default useUpload
