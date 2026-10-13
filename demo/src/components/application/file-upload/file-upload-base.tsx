import type { ComponentProps, ComponentPropsWithRef } from "react";
import { useId, useMemo, useRef, useState } from "react";
import type { FileIcon } from "@untitledui/file-icons";
import { FileIcon as FileTypeIcon } from "@untitledui/file-icons";
import { CheckCircle, DownloadCloud02, Loading02, Trash01, UploadCloud02, XCircle } from "@untitledui/icons";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/base/buttons/button";
import { ButtonUtility } from "@/components/base/buttons/button-utility";
import { ProgressBar } from "@/components/base/progress-indicators/progress-indicators";
import { cx } from "@/utils/cx";
import { Illustration } from "@/components/shared-assets/illustrations";
import { useTheme } from "@heroui/react";


/**
 * Returns a human-readable file size.
 * @param bytes - The size of the file in bytes.
 * @returns A string representing the file size in a human-readable format.
 */
export const getReadableFileSize = (bytes: number) => {
    if (bytes === 0) return "0 KB";

    const suffixes = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"];

    const i = Math.floor(Math.log(bytes) / Math.log(1024));

    return Math.floor(bytes / Math.pow(1024, i)) + " " + suffixes[i];
};

interface FileUploadDropZoneProps {
    /** The class name of the drop zone. */
    className?: string;
    /**
     * A hint text explaining what files can be dropped.
     */
    hint?: string;
    /**
     * Disables dropping or uploading files.
     */
    isDisabled?: boolean;
    /**
     * Specifies the types of files that the server accepts.
     * Examples: "image/*", ".pdf,image/*", "image/*,video/mpeg,application/pdf"
     */
    accept?: string;
    /**
     * Allows multiple file uploads.
     */
    allowsMultiple?: boolean;
    /**
     * Maximum file size in bytes.
     */
    maxSize?: number;
    /**
     * Callback function that is called with the list of dropped files
     * when files are dropped on the drop zone.
     */
    onDropFiles?: (files: FileList) => void;
    /**
     * Callback function that is called with the list of unaccepted files
     * when files are dropped on the drop zone.
     */
    onDropUnacceptedFiles?: (files: FileList) => void;
    /**
     * Callback function that is called with the list of files that exceed
     * the size limit when files are dropped on the drop zone.
     */
    onSizeLimitExceed?: (files: FileList) => void;
}

export const FileUploadDropZone = ({
    className,
    hint,
    isDisabled,
    accept,
    allowsMultiple = true,
    maxSize,
    onDropFiles,
    onDropUnacceptedFiles,
    onSizeLimitExceed,
}: FileUploadDropZoneProps) => {
    const id = useId();
    const inputRef = useRef<HTMLInputElement>(null);
    const [isInvalid, setIsInvalid] = useState(false);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const { theme } = useTheme();
  const isDark = useMemo(() => theme === 'dark', [theme])

    const isFileTypeAccepted = (file: File): boolean => {
        if (!accept) return true;

        // Split the accept string into individual types
        const acceptedTypes = accept.split(",").map((type) => type.trim());

        return acceptedTypes.some((acceptedType) => {
            // Handle file extensions (e.g., .pdf, .doc)
            if (acceptedType.startsWith(".")) {
                const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;
                return extension === acceptedType.toLowerCase();
            }

            // Handle wildcards (e.g., image/*)
            if (acceptedType.endsWith("/*")) {
                const typePrefix = acceptedType.split("/")[0];
                return file.type.startsWith(`${typePrefix}/`);
            }

            // Handle exact MIME types (e.g., application/pdf)
            return file.type === acceptedType;
        });
    };

    const handleDragIn = (event: React.DragEvent<HTMLDivElement>) => {
        if (isDisabled) return;

        event.preventDefault();
        event.stopPropagation();
        setIsDraggingOver(true);
    };

    const handleDragOut = (event: React.DragEvent<HTMLDivElement>) => {
        if (isDisabled) return;

        event.preventDefault();
        event.stopPropagation();
        setIsDraggingOver(false);
    };

    const processFiles = (files: File[]): void => {
        // Reset the invalid state when processing files.
        setIsInvalid(false);

        const acceptedFiles: File[] = [];
        const unacceptedFiles: File[] = [];
        const oversizedFiles: File[] = [];

        // If multiple files are not allowed, only process the first file
        const filesToProcess = allowsMultiple ? files : files.slice(0, 1);

        filesToProcess.forEach((file) => {
            // Check file size first
            if (maxSize && file.size > maxSize) {
                oversizedFiles.push(file);
                return;
            }

            // Then check file type
            if (isFileTypeAccepted(file)) {
                acceptedFiles.push(file);
            } else {
                unacceptedFiles.push(file);
            }
        });

        // Handle oversized files
        if (oversizedFiles.length > 0 && typeof onSizeLimitExceed === "function") {
            const dataTransfer = new DataTransfer();
            oversizedFiles.forEach((file) => dataTransfer.items.add(file));

            setIsInvalid(true);
            onSizeLimitExceed(dataTransfer.files);
        }

        // Handle accepted files
        if (acceptedFiles.length > 0 && typeof onDropFiles === "function") {
            const dataTransfer = new DataTransfer();
            acceptedFiles.forEach((file) => dataTransfer.items.add(file));
            onDropFiles(dataTransfer.files);
        }

        // Handle unaccepted files
        if (unacceptedFiles.length > 0 && typeof onDropUnacceptedFiles === "function") {
            const unacceptedDataTransfer = new DataTransfer();
            unacceptedFiles.forEach((file) => unacceptedDataTransfer.items.add(file));

            setIsInvalid(true);
            onDropUnacceptedFiles(unacceptedDataTransfer.files);
        }

        // Clear the input value to ensure the same file can be selected again
        if (inputRef.current) {
            inputRef.current.value = "";
        }
    };

    const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
        if (isDisabled) return;
        handleDragOut(event);
        processFiles(Array.from(event.dataTransfer.files));
    };

    const handleInputFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        processFiles(Array.from(event.target.files || []));
    };

    return (
        <div
            data-dropzone
            onDragOver={handleDragIn}
            onDragEnter={handleDragIn}
            onDragLeave={handleDragOut}
            onDragEnd={handleDragOut}
            onDrop={handleDrop}
            className={cx(
                "relative flex flex-col items-center gap-3 rounded-xl bg-background-tertiary px-6 py-10 placeholder-text-placeholder border-2 border-dashed border-neutral-300 overflow-clip",
                isDisabled && "cursor-not-allowed bg-secondary",
                className,
            )}
        >

        <div className={cx("transition duration-100 ease-linear bg-brand-500 opacity-0 w-full h-full absolute top-0 left-0 z-10", isDraggingOver && "opacity-20")}></div>

          <Illustration type="box" size="md" />


            <div className="flex flex-col gap-1 text-center">
                <div className="flex justify-center gap-1 text-center">
                    <input
                        ref={inputRef}
                        id={id}
                        type="file"
                        className="peer sr-only"
                        disabled={isDisabled}
                        accept={accept}
                        multiple={allowsMultiple}
                        onChange={handleInputFileChange}
                    />
                    <label htmlFor={id} className="flex cursor-pointer text-sm items-center">
                        <Button color="link-color" size="md" isDisabled={isDisabled} onClick={() => inputRef.current?.click()}>
                            Click to upload <span className="md:hidden">and attach files</span>
                        </Button>
                    </label>
                    <span className="text-sm max-md:hidden">or drag and drop</span>
                </div>
                <p className={cx("text-xs transition duration-100 ease-linear", isInvalid && "text-error-primary")}>
                    {hint || "SVG, PNG, JPG or GIF (max. 800x400px)"}
                </p>
            </div>
        </div>
    );
};

export interface FileListItemProps {
    /** The name of the file. */
    name: string;
    /** The size of the file. */
    size: number;
    /** The upload progress of the file. */
    progress: number;
    /** Whether the file failed to upload. */
    failed?: boolean;
    /**
     * True once the server-side step finished but a client-side follow-up
     * (e.g. writing the result to disk) still needs the user's input.
     * Renders a distinct "needs action" state -- separate from `failed` --
     * so a step that can be retried on its own doesn't push the user toward
     * "Try again", which would redo the whole (already-successful) upload.
     */
    needsAction?: boolean;
    /** Label for the `needsAction` button. @default "Save" */
    actionLabel?: string;
    /** Called when the `needsAction` button is clicked. */
    onAction?: () => void;
    /**
     * True while `progress` is a coarse in-flight estimate rather than real
     * completion (the server has no per-unit progress hook -- see
     * `packages/admin/CLAUDE.md`). Renders an animated, indeterminate fill
     * instead of trusting the number at face value, since a bar frozen at a
     * fixed percentage for minutes reads as stalled.
     */
    pending?: boolean;
    /** Status line shown instead of the file size, e.g. a server-reported stage. */
    statusText?: string;
    /** The type of the file. */
    type?: ComponentProps<typeof FileIcon>["type"];
    /** The class name of the file list item. */
    className?: string;
    /** The variant of the file icon. */
    fileIconVariant?: ComponentProps<typeof FileTypeIcon>["variant"];
    /** The function to call when the file is deleted. */
    onDelete?: () => void;
    /** The function to call when the file upload is retried. */
    onRetry?: () => void;
}

export const FileListItemProgressBar = ({ name, size, progress, failed, type, fileIconVariant, onDelete, onRetry, className }: FileListItemProps) => {
  const isComplete = progress === 100;
  const { theme } = useTheme();
  const isDark = useMemo(() => theme === 'dark', [theme])

    return (
        <motion.li
            layout="position"
            className={cx(
                "relative flex gap-3 rounded-xl bg-background p-4 ring-1 ring-secondary transition-shadow duration-100 ease-linear ring-inset",
                failed && "ring-2 ring-error",
                className,
            )}
        >
          <FileTypeIcon className="size-10 shrink-0" type={"zip"} variant={fileIconVariant ?? "default"} theme={isDark ? 'light' : 'dark'} />

            <div className="flex min-w-0 flex-1 flex-col items-start">
                <div className="flex w-full max-w-full min-w-0 flex-1">
                    <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-secondary">{name}</p>

                        <div className="mt-0.5 flex items-center gap-2">
                            <p className="truncate text-sm whitespace-nowrap text-tertiary">{getReadableFileSize(size)}</p>

                            <hr className="h-3 w-px rounded-t-full rounded-b-full border-none bg-border-primary" />

                            <div className="flex items-center gap-1">
                                {isComplete && <CheckCircle className="size-4 stroke-[2.5px] text-fg-success-primary" />}
                                {isComplete && <p className="text-sm font-medium text-success-primary">Complete</p>}

                                {!isComplete && !failed && <UploadCloud02 className="size-4 stroke-[2.5px] text-fg-quaternary" />}
                                {!isComplete && !failed && <p className="text-sm font-medium text-secondary">Uploading...</p>}

                                {failed && <XCircle className="size-4 text-fg-error-primary" />}
                                {failed && <p className="text-sm font-medium text-error-primary">Failed</p>}
                            </div>
                        </div>
                    </div>

                    <ButtonUtility color="tertiary" tooltip="Delete" icon={Trash01} size="xs" className="-mt-2 -mr-2 self-start" onClick={onDelete} />
                </div>

                {!failed && (
                    <div className="mt-1 w-full">
                        <ProgressBar labelPosition="right" max={100} min={0} value={progress} />
                    </div>
                )}

                {failed && (
                    <Button color="link-destructive" size="sm" onClick={onRetry} className="mt-1.5">
                        Try again
                    </Button>
                )}
            </div>
        </motion.li>
    );
};

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
    type,
    fileIconVariant,
    onDelete,
    onRetry,
    className,
}: FileListItemProps) => {
  const isComplete = progress === 100 && !needsAction;
  const { theme } = useTheme();
  const isDark = useMemo(() => theme === 'dark', [theme])

    return (
        <motion.li layout="position" className={cx("relative flex gap-3 overflow-hidden rounded-xl bg-primary p-4", className)}>
            {/* Progress fill -- while `pending`, the server only reports coarse
                stage transitions, not a real percentage, so an animated sweep
                communicates "still working" honestly instead of a bar frozen
                at a fixed number that reads as stalled. */}
            {pending ? (
                <motion.div
                    className="absolute inset-y-0 left-0 w-1/3 rounded-[inherit] bg-black/10 dark:bg-neutral-700/50"
                    animate={{ x: ["-100%", "300%"] }}
                    transition={{ repeat: Infinity, duration: 1.1, ease: "easeInOut" }}
                    role="progressbar"
                    aria-valuetext="In progress"
                />
            ) : (
                <div
                    style={{ transform: `translateX(-${100 - progress}%)` }}
                    className={cx("absolute inset-0 size-full bg-black/10 dark:bg-neutral-700/50 transition duration-75 ease-linear", isComplete && "opacity-0")}
                    role="progressbar"
                    aria-valuenow={progress}
                    aria-valuemin={0}
                    aria-valuemax={100}
                />
            )}
            {/* Inner ring. */}
            <div
                className={cx(
                    "absolute inset-0 size-full rounded-[inherit] ring-1 ring-secondary/40 transition duration-100 ease-linear ring-inset",
                    failed && "ring-2 ring-error",
                    needsAction && "ring-2 ring-[var(--color-fg-warning-primary)]",
                )}
            />
            <FileTypeIcon className="size-10 shrink-0" type={"zip"} variant={fileIconVariant ?? "default"} theme={isDark ? 'light' : 'dark'} />

            <div className="relative flex min-w-0 flex-1">
                <div className="relative flex min-w-0 flex-1 flex-col items-start">
                    <div className="w-full min-w-0 flex-1">
              <p className={cx("truncate text-sm font-medium text-pretty", (progress == 0 || progress != 100) && "font-bold")}>{name}</p>

                        <div className="mt-0.5 flex items-center gap-2">
                <p className={cx("truncate text-sm text-neutral-400", progress > 0 && "text-neutral-700 dark:text-neutral-200")}>
                    {failed ? "Conversion failed, please try again" : needsAction ? "Ready -- couldn't save automatically" : (statusText ?? getReadableFileSize(size))}
                </p>

                            {!failed && (
                                <>
                                    <hr className="h-3 w-px shrink-0 rounded-t-full rounded-b-full border-none bg-border-primary" />
                                    <div className="flex shrink-0 items-center gap-1">
                                        {isComplete && <CheckCircle className="size-4 stroke-[2.5px] text-fg-success-primary" />}
                                        {needsAction && <DownloadCloud02 className="size-4 stroke-[2.5px] text-fg-warning-primary" />}
                                        {!isComplete && !needsAction && (
                                            pending
                                                ? <Loading02 className="size-4 animate-spin stroke-[2.5px] text-fg-tertiary" />
                                                : <UploadCloud02 className="size-4 stroke-[2.5px] text-fg-tertiary" />
                                        )}

                                        {!needsAction && (
                                            <p className={cx("text-sm text-neutral-400", progress > 0 && "text-neutral-700 dark:text-neutral-200")}>{progress}%</p>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                    </div>

                    {failed && (
                        <Button color="link-destructive" size="sm" onClick={onRetry} className="mt-1.5">
                            Try again
                        </Button>
                    )}

                    {!failed && needsAction && (
                        <Button color="link-color" size="sm" onClick={onAction} className="mt-1.5">
                            {actionLabel}
                        </Button>
                    )}
                </div>

                <ButtonUtility color="tertiary" tooltip="Delete" icon={Trash01} size="xs" className="-mt-2 -mr-2 self-start" onClick={onDelete} />
            </div>
        </motion.li>
    );
};

const FileUploadRoot = (props: ComponentPropsWithRef<"div">) => (
    <div {...props} className={cx("flex flex-col gap-4", props.className)}>
        {props.children}
    </div>
);

const FileUploadList = (props: ComponentPropsWithRef<"ul">) => (
    <ul {...props} className={cx("flex flex-col gap-3", props.className)}>
        <AnimatePresence initial={false}>{props.children}</AnimatePresence>
    </ul>
);

export const FileUpload = {
    Root: FileUploadRoot,
    List: FileUploadList,
    DropZone: FileUploadDropZone,
    ListItemProgressBar: FileListItemProgressBar,
    ListItemProgressFill: FileListItemProgressFill,
};
