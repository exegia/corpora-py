import type { FC, SVGProps } from "react"
import {
  BookOpen,
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileVideo
} from "lucide-react"
import { cn } from "~/lib/utils"

type FileKind = {
  label: string
  icon: FC<SVGProps<SVGSVGElement>>
  /** Icon tint; the tile keeps the neutral muted background. */
  className: string
}

const KINDS: Record<string, FileKind> = {
  archive: { label: "Archive", icon: FileArchive, className: "text-amber-600 dark:text-amber-400" },
  pdf: { label: "PDF document", icon: FileText, className: "text-red-600 dark:text-red-400" },
  document: { label: "Document", icon: FileText, className: "text-blue-600 dark:text-blue-400" },
  spreadsheet: { label: "Spreadsheet", icon: FileSpreadsheet, className: "text-emerald-600 dark:text-emerald-400" },
  image: { label: "Image", icon: FileImage, className: "text-violet-600 dark:text-violet-400" },
  audio: { label: "Audio", icon: FileAudio, className: "text-pink-600 dark:text-pink-400" },
  video: { label: "Video", icon: FileVideo, className: "text-cyan-600 dark:text-cyan-400" },
  markup: { label: "Markup document", icon: FileCode, className: "text-orange-600 dark:text-orange-400" },
  book: { label: "E-book", icon: BookOpen, className: "text-teal-600 dark:text-teal-400" },
  generic: { label: "File", icon: File, className: "text-muted-foreground" }
}

const EXTENSION_TO_KIND: Record<string, keyof typeof KINDS> = {
  zip: "archive",
  tar: "archive",
  gz: "archive",
  tgz: "archive",
  rar: "archive",
  corpus: "archive",
  pdf: "pdf",
  doc: "document",
  docx: "document",
  txt: "document",
  text: "document",
  md: "document",
  csv: "spreadsheet",
  tsv: "spreadsheet",
  xls: "spreadsheet",
  xlsx: "spreadsheet",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  svg: "image",
  webp: "image",
  mp3: "audio",
  wav: "audio",
  ogg: "audio",
  m4a: "audio",
  mp4: "video",
  mov: "video",
  webm: "video",
  mkv: "video",
  xml: "markup",
  tei: "markup",
  html: "markup",
  htm: "markup",
  epub: "book"
}

export const fileExtension = (filename: string): string => {
  const match = /\.([^./]+)$/.exec(filename)
  return (match?.[1] ?? "").toLowerCase()
}

export const fileKind = (filename: string): FileKind =>
  KINDS[EXTENSION_TO_KIND[fileExtension(filename)] ?? "generic"]

/**
 * File-type icon tile keyed off the file extension, falling back to a
 * generic file glyph when no dedicated icon exists.
 */
export function FileTypeIcon({
                               filename,
                               className,
                               iconClassName
                             }: {
  filename: string
  className?: string
  iconClassName?: string
}) {
  const kind = fileKind(filename)
  const Icon = kind.icon
  return (
    <div
      className={cn(
        "flex size-14 shrink-0 items-center justify-center rounded-xl border border-border bg-muted",
        className
      )}
      role="img"
      aria-label={kind.label}
    >
      <Icon className={cn("size-7", kind.className, iconClassName)} aria-hidden="true" />
    </div>
  )
}
