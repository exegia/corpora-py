import { EXTENSION_TO_FORMAT } from "./source-format"

/**
 * Client-side ZIP inspection: reads the archive's central directory (entry
 * names + sizes only, never the whole file) so an uploaded ZIP can be
 * routed *before* it hits the conversion service:
 *
 * - `.tf` files inside      -> a Text-Fabric dataset -> send as `tf_zip`
 *                              (the existing behavior).
 * - only TEI/XML documents inside (two or more) -> a TEI corpus -> send as
 *                              `tei_zip` (the server extracts and converts
 *                              every member into one dataset).
 * - exactly one convertible document inside (.tei/.xml/.epub/.html/.pdf/
 *   .txt/...)               -> extract it in the browser and continue the
 *                              normal single-file flow.
 * - anything else           -> reject with a message describing what was
 *                              found, since the service has no converter
 *                              for it (e.g. a mixed bag of PDFs and EPUBs).
 *
 * ZIP64 or otherwise unparseable-but-plausible archives fall back to the
 * pre-inspection behavior (send as `tf_zip` and let the server validate) --
 * inspection is an optimization for clearer, earlier feedback, never a new
 * way to lose an upload that would previously have worked.
 */

export type ZipEntry = {
  /** Full path inside the archive, e.g. "dataset/otype.tf". */
  name: string
  size: number
  compressedSize: number
  /** ZIP compression method: 0 = stored, 8 = deflate. */
  method: number
  /** Byte offset of the entry's local file header. */
  headerOffset: number
}

export type ZipInspection =
  | { kind: "tf"; notes: string[] }
  | { kind: "tei"; notes: string[] }
  | { kind: "document"; entry: ZipEntry; notes: string[] }
  | { kind: "fallback"; notes: string[] }
  | { kind: "unsupported"; message: string }

const EOCD_SIGNATURE = 0x06054b50
const CENTRAL_SIGNATURE = 0x02014b50
const LOCAL_SIGNATURE = 0x04034b50
// EOCD is 22 bytes + up to 65535 bytes of archive comment.
const EOCD_SEARCH_SPAN = 22 + 65535

const extensionOf = (name: string): string => {
  const match = /\.[^./]+$/.exec(name)
  return (match?.[0] ?? "").toLowerCase()
}

const basename = (name: string): string => name.split("/").pop() ?? name

// macOS resource forks and hidden housekeeping files say nothing about what
// the archive *is* -- keep them out of classification and counts.
const isNoise = (name: string): boolean =>
  name.startsWith("__MACOSX/") || basename(name).startsWith(".")

const readCentralDirectory = async (file: File): Promise<ZipEntry[] | null> => {
  const tailStart = Math.max(0, file.size - EOCD_SEARCH_SPAN)
  const tail = new DataView(await file.slice(tailStart, file.size).arrayBuffer())

  let eocd = -1
  for (let i = tail.byteLength - 22; i >= 0; i--) {
    if (tail.getUint32(i, true) === EOCD_SIGNATURE) {
      eocd = i
      break
    }
  }
  if (eocd === -1) return null

  const entryCount = tail.getUint16(eocd + 10, true)
  const directorySize = tail.getUint32(eocd + 12, true)
  const directoryOffset = tail.getUint32(eocd + 16, true)
  // ZIP64 markers -- the 32-bit fields can't describe this archive.
  if (
    entryCount === 0xffff ||
    directorySize === 0xffffffff ||
    directoryOffset === 0xffffffff
  ) {
    return null
  }

  const directory = new DataView(
    await file.slice(directoryOffset, directoryOffset + directorySize).arrayBuffer()
  )
  const decoder = new TextDecoder()
  const entries: ZipEntry[] = []
  let cursor = 0
  for (let i = 0; i < entryCount; i++) {
    if (
      cursor + 46 > directory.byteLength ||
      directory.getUint32(cursor, true) !== CENTRAL_SIGNATURE
    ) {
      return null
    }
    const method = directory.getUint16(cursor + 10, true)
    const compressedSize = directory.getUint32(cursor + 20, true)
    const size = directory.getUint32(cursor + 24, true)
    const nameLength = directory.getUint16(cursor + 28, true)
    const extraLength = directory.getUint16(cursor + 30, true)
    const commentLength = directory.getUint16(cursor + 32, true)
    const headerOffset = directory.getUint32(cursor + 42, true)
    const name = decoder.decode(
      new Uint8Array(directory.buffer, directory.byteOffset + cursor + 46, nameLength)
    )
    if (!name.endsWith("/")) {
      entries.push({ name, size, compressedSize, method, headerOffset })
    }
    cursor += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

const countByExtension = (entries: ZipEntry[]): Map<string, number> => {
  const counts = new Map<string, number>()
  for (const entry of entries) {
    const extension = extensionOf(entry.name) || "(none)"
    counts.set(extension, (counts.get(extension) ?? 0) + 1)
  }
  return counts
}

const describeCounts = (counts: Map<string, number>): string =>
  [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([extension, count]) => `${count} ${extension}`)
    .join(", ")

/** Extensions convertible as a single document (everything but .zip itself). */
const DOCUMENT_EXTENSIONS = new Set(
  Object.keys(EXTENSION_TO_FORMAT).filter((extension) => extension !== ".zip")
)

export const inspectZip = async (file: File): Promise<ZipInspection> => {
  let entries: ZipEntry[] | null
  try {
    entries = await readCentralDirectory(file)
  } catch {
    entries = null
  }
  if (entries === null) {
    return {
      kind: "fallback",
      notes: [
        "Archive could not be inspected in the browser (ZIP64 or unusual layout) — sending as a Text-Fabric ZIP for the server to validate."
      ]
    }
  }
  if (entries.length === 0) {
    return { kind: "unsupported", message: `"${file.name}" is an empty archive.` }
  }

  const relevant = entries.filter((entry) => !isNoise(entry.name))
  const counts = countByExtension(relevant)
  const inventory = `Archive inspected: ${relevant.length} file${relevant.length === 1 ? "" : "s"} (${describeCounts(counts)})`

  const tfCount = counts.get(".tf") ?? 0
  if (tfCount > 0) {
    return {
      kind: "tf",
      notes: [inventory, `${tfCount} Text-Fabric (.tf) files found — treating as a Text-Fabric dataset`]
    }
  }

  const documents = relevant.filter((entry) =>
    DOCUMENT_EXTENSIONS.has(extensionOf(entry.name))
  )
  if (documents.length === 1) {
    const entry = documents[0]!
    return {
      kind: "document",
      entry,
      notes: [
        inventory,
        `Single convertible document found — extracting ${basename(entry.name)} from the archive`
      ]
    }
  }
  if (documents.length > 1) {
    // A multi-document archive is convertible only when it's a TEI corpus
    // (every member .tei/.xml) -- the server's tei_zip converter walks all
    // of them into one dataset.
    const allTei = documents.every((entry) =>
      [".tei", ".xml"].includes(extensionOf(entry.name))
    )
    if (allTei) {
      return {
        kind: "tei",
        notes: [
          inventory,
          `${documents.length} TEI/XML documents found — treating as a TEI corpus`
        ]
      }
    }
    return {
      kind: "unsupported",
      message:
        `"${file.name}" contains ${documents.length} documents (${describeCounts(countByExtension(documents))}). ` +
        "Multi-document archives are only supported as Text-Fabric datasets (.tf files) " +
        "or TEI/XML corpora — upload the documents one at a time instead."
    }
  }
  return {
    kind: "unsupported",
    message:
      `No convertible files found inside "${file.name}" (${describeCounts(counts)}). ` +
      "A ZIP must contain a Text-Fabric dataset (.tf files) or a single " +
      `${[...DOCUMENT_EXTENSIONS].join("/")} document.`
  }
}

/**
 * Extracts one entry from the archive into a standalone `File`, using the
 * browser's native inflate (`DecompressionStream`) -- no ZIP library needed.
 * Returns null when the entry uses a compression method we can't decode.
 */
export const extractZipEntry = async (
  file: File,
  entry: ZipEntry
): Promise<File | null> => {
  if (entry.method !== 0 && entry.method !== 8) return null

  // Name/extra lengths in the LOCAL header can differ from the central
  // directory's copy -- the data offset must come from the local record.
  const local = new DataView(
    await file.slice(entry.headerOffset, entry.headerOffset + 30).arrayBuffer()
  )
  if (local.getUint32(0, true) !== LOCAL_SIGNATURE) return null
  const dataStart =
    entry.headerOffset +
    30 +
    local.getUint16(26, true) +
    local.getUint16(28, true)
  const compressed = file.slice(dataStart, dataStart + entry.compressedSize)

  let bytes: ArrayBuffer
  if (entry.method === 0) {
    bytes = await compressed.arrayBuffer()
  } else {
    const inflated = compressed
      .stream()
      .pipeThrough(new DecompressionStream("deflate-raw"))
    bytes = await new Response(inflated).arrayBuffer()
  }
  return new File([bytes], basename(entry.name), {
    lastModified: file.lastModified
  })
}
