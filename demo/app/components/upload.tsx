import { FileUpload } from "@/components/application/file-upload/file-upload-base"
import { useUpload } from "../hooks/use-upload"

// Keep in sync with `_EXTENSION_TO_FORMAT` in src/corpora_py/bridge.py --
// a source format there is auto-detected from the filename extension, so
// anything not in that map fails server-side after a full upload+decode
// round trip. Restricting the picker/drop target here catches that earlier.
const ACCEPTED_EXTENSIONS = ".epub,.html,.htm,.xml,.tei,.pdf,.txt,.text"

export const FileUploadProgressFill = (props: { isDisabled?: boolean }) => {
  const { uploads, uploadFile, deleteUpload, retryUpload, saveUpload } = useUpload()

  const handleDropFiles = (files: FileList) => {
    Array.from(files).forEach((file) => void uploadFile(file))
  }

  return (
    <FileUpload.Root>
      <FileUpload.DropZone
        isDisabled={props.isDisabled}
        accept={ACCEPTED_EXTENSIONS}
        hint="EPUB, HTML, TEI/XML, PDF, or plain text"
        onDropFiles={handleDropFiles}
      />

      <FileUpload.List>
        {Object.values(uploads).map((upload) => (
          <FileUpload.ListItemProgressFill
            key={upload.id}
            name={upload.name}
            size={upload.size}
            progress={upload.progress}
            failed={upload.status === "error"}
            // "ready" = the server finished converting and the `.corpus`
            // bytes are already downloaded, but the local save-to-disk step
            // hasn't completed yet -- see use-upload.ts's `trySave`.
            needsAction={upload.status === "ready"}
            actionLabel="Save file"
            onAction={() => saveUpload(upload.id)}
            // The server has no per-unit progress hook (see
            // packages/admin/CLAUDE.md) -- "queued"/"converting" only ever
            // report coarse stage transitions, so the bar shows an
            // indeterminate animation rather than a number that would sit
            // frozen for the whole conversion.
            pending={upload.status === "queued" || upload.status === "converting"}
            statusText={upload.lastLog ?? undefined}
            fileIconVariant="gray"

            onDelete={() => deleteUpload(upload.id)}
            onRetry={() => retryUpload(upload.id)}
          />
        ))}
      </FileUpload.List>
    </FileUpload.Root>
  )
}
