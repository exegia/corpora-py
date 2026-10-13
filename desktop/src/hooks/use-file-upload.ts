import {
    useCallback,
    useEffect,
    useRef,
    useState,
    type ChangeEvent,
    type DragEvent,
    type InputHTMLAttributes,
    type Ref
} from "react"

export type FileMetadata = { name: string; size: number; type: string; url: string; id: string }
export type FileWithPreview = { file: File | FileMetadata; id: string; preview?: string }
export type FileUploadOptions = {
    maxFiles?: number
    maxSize?: number
    accept?: string
    multiple?: boolean
    initialFiles?: FileMetadata[]
    onFilesChange?: (files: FileWithPreview[]) => void
    onFilesAdded?: (files: FileWithPreview[]) => void
    onError?: (errors: string[]) => void
}
export type FileUploadState = { files: FileWithPreview[]; isDragging: boolean; errors: string[] }
export type FileUploadActions = {
    addFiles: (files: FileList | File[]) => void
    removeFile: (id: string) => void
    clearFiles: () => void
    clearErrors: () => void
    handleDragEnter: (event: DragEvent<HTMLElement>) => void
    handleDragLeave: (event: DragEvent<HTMLElement>) => void
    handleDragOver: (event: DragEvent<HTMLElement>) => void
    handleDrop: (event: DragEvent<HTMLElement>) => void
    handleFileChange: (event: ChangeEvent<HTMLInputElement>) => void
    openFileDialog: () => void
    getInputProps: (
        props?: InputHTMLAttributes<HTMLInputElement>
    ) => InputHTMLAttributes<HTMLInputElement> & { ref: Ref<HTMLInputElement> }
}

export function validateUploadFile(
    file: Pick<File, "name" | "size" | "type">,
    { maxSize = Infinity, accept = "*" }: FileUploadOptions
): string | null {
    if (file.size === 0) return `“${file.name}” is empty. Choose a file with content.`
    if (file.size > maxSize) return `“${file.name}” exceeds the ${formatBytes(maxSize)} limit.`
    const types = accept
        .split(",")
        .map((type) => type.trim().toLowerCase())
        .filter(Boolean)
    const accepted = types.some(
        (type) =>
            type === "*" ||
            (type.startsWith(".")
                ? file.name.toLowerCase().endsWith(type)
                : type.endsWith("/*")
                  ? file.type.toLowerCase().startsWith(type.slice(0, -1))
                  : file.type.toLowerCase() === type)
    )
    return accepted ? null : `“${file.name}” is not a supported source file.`
}

export function useFileUpload(options: FileUploadOptions = {}): [FileUploadState, FileUploadActions] {
    const { multiple = false, maxFiles = Infinity, onFilesChange, onFilesAdded, onError } = options
    const [state, setState] = useState<FileUploadState>(() => ({
        files: (options.initialFiles ?? []).map((file) => ({ file, id: file.id, preview: file.url })),
        isDragging: false,
        errors: []
    }))
    const filesRef = useRef(state.files)
    const inputRef = useRef<HTMLInputElement>(null)
    const previewsRef = useRef(new Set<string>())

    useEffect(
        () => () => {
            for (const url of previewsRef.current) URL.revokeObjectURL(url)
            previewsRef.current.clear()
        },
        []
    )

    const revoke = useCallback((entries: FileWithPreview[]) => {
        for (const entry of entries) {
            if (entry.preview && previewsRef.current.delete(entry.preview)) URL.revokeObjectURL(entry.preview)
        }
    }, [])

    const replaceFiles = useCallback(
        (files: FileWithPreview[], errors: string[] = []) => {
            filesRef.current = files
            setState((previous) => ({ ...previous, files, errors }))
            // Notify outside the React state updater: the consumer can update its own form.
            onFilesChange?.(files)
            if (inputRef.current) inputRef.current.value = ""
        },
        [onFilesChange]
    )

    const clearFiles = useCallback(() => {
        revoke(filesRef.current)
        replaceFiles([])
    }, [replaceFiles, revoke])

    const addFiles = useCallback(
        (incoming: FileList | File[]) => {
            if (inputRef.current?.disabled) return
            const files = Array.from(incoming)
            if (!files.length) return
            const errors: string[] = []
            if (!multiple && files.length > 1) errors.push("Choose one source file per conversion.")
            if (multiple && filesRef.current.length + files.length > maxFiles)
                errors.push(`Choose no more than ${maxFiles} files.`)
            for (const file of files) {
                const error = validateUploadFile(file, options)
                if (error) errors.push(error)
            }
            if (errors.length) {
                setState((previous) => ({ ...previous, errors }))
                onError?.(errors)
                if (inputRef.current) inputRef.current.value = ""
                return
            }
            const additions = files
                .filter(
                    (file) =>
                        !multiple ||
                        !filesRef.current.some(
                            (entry) => entry.file.name === file.name && entry.file.size === file.size
                        )
                )
                .map((file) => {
                    // Documents don't need blob previews; only allocate URLs for images.
                    const preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined
                    if (preview) previewsRef.current.add(preview)
                    return { file, id: crypto.randomUUID(), preview }
                })
            if (!multiple) revoke(filesRef.current)
            replaceFiles(multiple ? [...filesRef.current, ...additions] : additions)
            onFilesAdded?.(additions)
        },
        [multiple, maxFiles, options, onError, onFilesAdded, replaceFiles, revoke]
    )

    const removeFile = useCallback(
        (id: string) => {
            revoke(filesRef.current.filter((entry) => entry.id === id))
            replaceFiles(filesRef.current.filter((entry) => entry.id !== id))
        },
        [replaceFiles, revoke]
    )
    const clearErrors = useCallback(() => setState((previous) => ({ ...previous, errors: [] })), [])
    const handleDragOver = useCallback((event: DragEvent<HTMLElement>) => {
        event.preventDefault()
        event.stopPropagation()
    }, [])
    const handleDragEnter = useCallback((event: DragEvent<HTMLElement>) => {
        event.preventDefault()
        event.stopPropagation()
        if (!inputRef.current?.disabled) setState((previous) => ({ ...previous, isDragging: true }))
    }, [])
    const handleDragLeave = useCallback((event: DragEvent<HTMLElement>) => {
        event.preventDefault()
        event.stopPropagation()
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return
        setState((previous) => ({ ...previous, isDragging: false }))
    }, [])
    const handleDrop = useCallback(
        (event: DragEvent<HTMLElement>) => {
            event.preventDefault()
            event.stopPropagation()
            setState((previous) => ({ ...previous, isDragging: false }))
            if (!inputRef.current?.disabled) addFiles(event.dataTransfer.files)
        },
        [addFiles]
    )
    const handleFileChange = useCallback(
        (event: ChangeEvent<HTMLInputElement>) => {
            if (event.target.files) addFiles(event.target.files)
        },
        [addFiles]
    )
    const openFileDialog = useCallback(() => {
        if (!inputRef.current?.disabled) inputRef.current?.click()
    }, [])
    const getInputProps = useCallback(
        (props: InputHTMLAttributes<HTMLInputElement> = {}) => ({
            ...props,
            type: "file" as const,
            accept: options.accept ?? "*",
            multiple,
            ref: inputRef,
            onChange: (event: ChangeEvent<HTMLInputElement>) => {
                handleFileChange(event)
                props.onChange?.(event)
            }
        }),
        [handleFileChange, multiple, options.accept]
    )

    return [
        state,
        {
            addFiles,
            removeFile,
            clearFiles,
            clearErrors,
            handleDragEnter,
            handleDragLeave,
            handleDragOver,
            handleDrop,
            handleFileChange,
            openFileDialog,
            getInputProps
        }
    ]
}

export function formatBytes(bytes: number, decimals = 1): string {
    if (bytes <= 0) return "0 B"
    if (!Number.isFinite(bytes)) return "unlimited"
    const units = ["B", "KiB", "MiB", "GiB", "TiB"]
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
    return `${Number((bytes / 1024 ** index).toFixed(Math.max(0, decimals)))} ${units[index]}`
}
