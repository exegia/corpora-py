import { FileType } from "@/components/reui/file-type"
import { SOURCE_FORMATS } from "@/lib/conversion"

/** The requested file-type block, narrowed to formats the converter accepts. */
export function SupportedConversionSources() {
    return (
        <ul
            aria-label="Supported source formats"
            className="flex flex-wrap gap-x-4 gap-y-3">
            {SOURCE_FORMATS.map((format) => (
                <li
                    key={format.value}
                    className="flex items-center gap-2 text-xs text-muted-foreground">
                    <FileType
                        type={format.value.endsWith("_zip") ? "zip" : format.value === "plain" ? "txt" : format.value}
                        variant="mono"
                        className="size-5"
                        aria-hidden="true"
                    />
                    {format.label}
                </li>
            ))}
        </ul>
    )
}
