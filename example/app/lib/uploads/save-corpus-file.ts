type SaveFilePicker = (options: {
  suggestedName: string
  types: { description: string; accept: Record<string, string[]> }[]
}) => Promise<{
  createWritable: () => Promise<{
    write: (data: Blob) => Promise<void>
    close: () => Promise<void>
  }>
}>

// Saves via the File System Access API's native save-as dialog where
// available (desktop webviews backing ElectroBun); falls back to a plain
// anchor-download for browsers that don't support it.
export const saveCorpusFile = async (
  filename: string,
  blob: Blob
): Promise<void> => {
  const showSaveFilePicker = (
    window as unknown as { showSaveFilePicker?: SaveFilePicker }
  ).showSaveFilePicker

  if (showSaveFilePicker) {
    try {
      const handle = await showSaveFilePicker({
        suggestedName: filename,
        types: [
          {
            description: "Corpus archive",
            accept: { "application/octet-stream": [".corpus"] }
          }
        ]
      })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      return
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return
      throw error
    }
  }

  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
