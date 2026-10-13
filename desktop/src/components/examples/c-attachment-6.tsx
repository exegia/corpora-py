import { Upload, X } from "lucide-react"
import {
    Attachment,
    AttachmentAction,
    AttachmentActions,
    AttachmentContent,
    AttachmentDescription,
    AttachmentMedia,
    AttachmentTitle,
    AttachmentTrigger
} from "@/components/ui/attachment"
import { FileType, getFileType } from "@/components/reui/file-type"
import type { FileUploadActions, FileUploadState } from "@/hooks/use-file-upload"
import { formatBytes, MAX_UPLOAD_BYTES } from "@/lib/conversion"
import { cn } from "@/lib/utils"

export function ConversionSourceAttachment({
    upload,
    actions,
    disabled = false
}: {
    upload: FileUploadState
    actions: FileUploadActions
    disabled?: boolean
}) {
    const entry = upload.files[0]
    return (
        <div className="flex flex-col gap-3">
            <Attachment
                state="idle"
                className={cn("w-full rounded-xl p-3", upload.isDragging && "border-primary bg-accent")}
                onDragEnter={actions.handleDragEnter}
                onDragLeave={actions.handleDragLeave}
                onDragOver={actions.handleDragOver}
                onDrop={actions.handleDrop}>
                <AttachmentMedia>
                    <Upload
                        aria-hidden="true"
                        strokeWidth={1.5}
                    />
                </AttachmentMedia>
                <AttachmentContent>
                    <AttachmentTitle>
                        {upload.isDragging
                            ? "Drop your source here"
                            : entry
                              ? "Replace source file"
                              : "Choose a source file"}
                    </AttachmentTitle>
                    <AttachmentDescription className="whitespace-normal">
                        Browse or drop one file · up to {formatBytes(MAX_UPLOAD_BYTES)}
                    </AttachmentDescription>
                </AttachmentContent>
                <AttachmentTrigger
                    type="button"
                    disabled={disabled}
                    aria-label={entry ? "Replace conversion source file" : "Choose conversion source file"}
                    onClick={actions.openFileDialog}
                />
                <input
                    {...actions.getInputProps({ disabled, "aria-label": "Conversion source file" })}
                    className="sr-only"
                    tabIndex={-1}
                />
            </Attachment>
            {entry && (
                <Attachment
                    state="done"
                    className="w-full rounded-xl">
                    <AttachmentMedia className="bg-transparent">
                        <FileType
                            type={getFileType(entry.file.name)}
                            variant="mono"
                            className="size-8"
                            aria-hidden="true"
                        />
                    </AttachmentMedia>
                    <AttachmentContent>
                        <AttachmentTitle title={entry.file.name}>{entry.file.name}</AttachmentTitle>
                        <AttachmentDescription>
                            {formatBytes(entry.file.size)} · Selected, not yet submitted
                        </AttachmentDescription>
                    </AttachmentContent>
                    <AttachmentActions>
                        <AttachmentAction
                            type="button"
                            size="icon"
                            disabled={disabled}
                            aria-label={`Remove source file ${entry.file.name}`}
                            onClick={() => actions.removeFile(entry.id)}>
                            <X aria-hidden="true" />
                        </AttachmentAction>
                    </AttachmentActions>
                </Attachment>
            )}
            {upload.errors.length > 0 && (
                <ul
                    role="alert"
                    className="flex flex-col gap-1 text-sm text-destructive-foreground">
                    {upload.errors.map((error) => (
                        <li key={error}>{error}</li>
                    ))}
                </ul>
            )}
        </div>
    )
}
