import type { ComponentProps } from "react"
import { Archive, CloudDownload, CloudUpload } from "lucide-react"
import { Button } from "@astryxdesign/core/Button"
import { Card } from "@astryxdesign/core/Card"
import { FileInput, type FileInputStatus } from "@astryxdesign/core/FileInput"
import { HStack } from "@astryxdesign/core/HStack"
import { Icon } from "@astryxdesign/core/Icon"
import { IconButton } from "@astryxdesign/core/IconButton"
import { List } from "@astryxdesign/core/List"
import { ProgressBar } from "@astryxdesign/core/ProgressBar"
import { Spinner } from "@astryxdesign/core/Spinner"
import { Text } from "@astryxdesign/core/Text"
import { VStack } from "@astryxdesign/core/VStack"

/**
 * Returns a human-readable file size.
 */
export const getReadableFileSize = (bytes: number) => {
  if (bytes === 0) return "0 KB"

  const suffixes = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
  const i = Math.floor(Math.log(bytes) / Math.log(1024))

  return Math.floor(bytes / Math.pow(1024, i)) + " " + suffixes[i]
}

interface FileUploadDropZoneProps {
  className?: string
  status?: FileInputStatus
  hint?: string
  isDisabled?: boolean
  accept?: string
  allowsMultiple?: boolean
  maxSize?: number
  onDropFiles?: (files: FileList) => void
  /** @deprecated FileInput validates rejected types internally and surfaces an error status. */
  onDropUnacceptedFiles?: (files: FileList) => void
  /** @deprecated FileInput validates size limits via `maxSize` and surfaces an error status. */
  onSizeLimitExceed?: (files: FileList) => void
}

const toFileList = (files: File | File[]): FileList => {
  const dataTransfer = new DataTransfer()
  for (const file of Array.isArray(files) ? files : [files]) {
    dataTransfer.items.add(file)
  }
  return dataTransfer.files
}

export const FileUploadDropZone = ({
                                     hint,
                                     isDisabled,
                                     accept,
                                     status,
                                     allowsMultiple = true,
                                     maxSize,
                                     onDropFiles
                                   }: FileUploadDropZoneProps) => {
  const handleChange = (files: File | File[] | null) => {
    if (!files) return

    if (typeof onDropFiles !== "function") {
      console.error("onDropFiles handler is missing")
      return
    }

    onDropFiles(toFileList(files))
  }

  return (
    <FileInput
      label="Upload file"
      isLabelHidden
      mode="dropzone"
      accept={accept}
      isMultiple={allowsMultiple}
      maxSize={maxSize}
      isDisabled={isDisabled}
      status={status}
      value={null}
      width={"100%"}
      className="h-1/2 w-full"
      onChange={handleChange}
      placeholder="Drag your file over to start the conversion"
      description={hint ?? "SVG, PNG, JPG or GIF (max. 800x400px)"}
    />
  )
}

export interface FileListItemProps {
  name: string
  size: number
  progress: number
  failed?: boolean
  needsAction?: boolean
  actionLabel?: string
  onAction?: () => void
  pending?: boolean
  statusText?: string
  type?: string
  className?: string
  fileIconVariant?: string
  onDelete?: () => void
  onRetry?: () => void
}

const fileIcon = <Icon icon={Archive} size="lg" color="secondary" />

const UploadStatus = ({
                        failed,
                        needsAction,
                        pending,
                        progress
                      }: Pick<FileListItemProps, "failed" | "needsAction" | "pending" | "progress">) => {
  const isComplete = progress === 100 && !needsAction

  if (failed) {
    return (
      <HStack gap={1} vAlign="center">
        <Icon icon="error" size="sm" color="error" />
        <Text type="supporting" className="text-red-700 dark:text-red-300">Failed</Text>
      </HStack>
    )
  }

  if (isComplete) {
    return (
      <HStack gap={1} vAlign="center">
        <Icon icon="success" size="sm" color="success" />
        <Text type="supporting" className="text-green-700 dark:text-green-200">Complete</Text>
      </HStack>
    )
  }

  if (needsAction) {
    return (
      <HStack gap={1} vAlign="center">
        <Icon icon={CloudDownload} size="sm" color="warning" />
        <Text type="supporting" color="accent">Ready</Text>
      </HStack>
    )
  }

  return (
    <HStack gap={1} vAlign="center">
      {pending
        ? <Spinner size="sm" aria-label="Converting" />
        : <Icon icon={CloudUpload} size="sm" color="tertiary" />}
      {!needsAction && (
        <Text type="supporting" color="secondary">
          {pending ? "Converting…" : `${progress}%`}
        </Text>
      )}
    </HStack>
  )
}

export const FileListItemProgressBar = ({
                                          name,
                                          size,
                                          progress,
                                          failed,
                                          onDelete,
                                          onRetry
                                        }: FileListItemProps) => {
  const isComplete = progress === 100

  return (
    <Card padding={4}>
      <VStack gap={2}>
        <HStack gap={3} vAlign="start">
          {fileIcon}
          <VStack gap={1} hAlign="stretch">
            <HStack gap={2} vAlign="center" hAlign="between">
              <Text type="label" maxLines={1}>{name}</Text>
              {onDelete && (
                <IconButton
                  label="Delete"
                  tooltip="Delete"
                  variant="ghost"
                  size="sm"
                  icon={<Icon icon="close" size="sm" />}
                  onClick={onDelete}
                />
              )}
            </HStack>
            <HStack gap={2} vAlign="center">
              <Text type="supporting" color="secondary">{getReadableFileSize(size)}</Text>
              <DividerDot />
              <UploadStatus failed={failed} progress={progress} />
            </HStack>
          </VStack>
        </HStack>

        {!failed && (
          <ProgressBar
            label={`Upload progress for ${name}`}
            isLabelHidden
            value={progress}
            variant={isComplete ? "success" : "accent"}
            hasValueLabel
          />
        )}

        {failed && onRetry && (
          <Button label="Try again" variant="destructive" size="sm" onClick={onRetry} />
        )}
      </VStack>
    </Card>
  )
}

export const FileListItemProgressFill = ({
                                           name,
                                           size,
                                           progress,
                                           failed,
                                           needsAction,
                                           actionLabel = "Save",
                                           onAction,
                                           pending,
                                           statusText,
                                           onDelete,
                                           onRetry
                                         }: FileListItemProps) => {
  const isComplete = progress === 100 && !needsAction
  const statusLine = failed
    ? "Conversion failed, please try again"
    : needsAction
      ? "Ready — couldn't save automatically"
      : (statusText ?? getReadableFileSize(size))

  return (
    <Card padding={4}>
      <VStack gap={2}>
        {!failed && (
          <ProgressBar
            label={`Conversion progress for ${name}`}
            isLabelHidden
            value={pending ? 0 : progress}
            isIndeterminate={pending}
            variant={
              failed ? "error"
                : needsAction ? "warning"
                  : isComplete ? "success"
                    : "accent"
            }
            hasValueLabel={!pending && !needsAction}
          />
        )}

        <HStack gap={3} vAlign="start">
          {fileIcon}
          <VStack gap={1} hAlign="stretch">
            <HStack gap={2} vAlign="center" hAlign="between">
              <Text type="label" maxLines={1}>{name}</Text>
              {onDelete && (
                <IconButton
                  label="Delete"
                  tooltip="Delete"
                  variant="ghost"
                  size="sm"
                  icon={<Icon icon="close" size="sm" />}
                  onClick={onDelete}
                />
              )}
            </HStack>
            <HStack gap={2} vAlign="center">
              <Text type="supporting" color="secondary">{statusLine}</Text>
              {!failed && (
                <>
                  <DividerDot />
                  <UploadStatus
                    failed={failed}
                    needsAction={needsAction}
                    pending={pending}
                    progress={progress}
                  />
                </>
              )}
            </HStack>
          </VStack>
        </HStack>

        {failed && onRetry && (
          <Button label="Try again" variant="destructive" size="sm" onClick={onRetry} />
        )}

        {!failed && needsAction && onAction && (
          <Button label={actionLabel} variant="primary" size="sm" onClick={onAction} />
        )}
      </VStack>
    </Card>
  )
}

const DividerDot = () => (
  <Text type="supporting" color="disabled" aria-hidden="true">·</Text>
)

const FileUploadRoot = (props: ComponentProps<typeof VStack>) => (
  <VStack gap={4} {...props} />
)

const FileUploadList = (props: ComponentProps<typeof List>) => (
  <List density="balanced" {...props} />
)

export const FileUpload = {
  Root: FileUploadRoot,
  List: FileUploadList,
  DropZone: FileUploadDropZone,
  ListItemProgressBar: FileListItemProgressBar,
  ListItemProgressFill: FileListItemProgressFill
}
