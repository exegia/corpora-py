// Mirrors `_EXTENSION_TO_FORMAT` in packages/admin/src/admin/services/api.py's
// `SourceFormat` enum values -- `POST /convert`'s `source_format` field is
// required (there's no server-side auto-detection), so the UI has to supply
// one. Generic XML preserves its own vocabulary; C-USX recognizes an actual
// TEI root without guessing TEI semantics for every XML upload.
export const EXTENSION_TO_FORMAT: Record<string, string> = {
  ".epub": "epub",
  ".html": "html",
  ".xml": "xml",
  ".tei": "tei",
  ".pdf": "pdf",
  ".txt": "plain",
  ".md": "markdown",
  ".markdown": "markdown",
  ".zip": "tf_zip",
}

export const detectSourceFormat = (filename: string): string => {
  const match = /\.[^./]+$/.exec(filename)
  const extension = (match?.[0] ?? "").toLowerCase()
  const format = EXTENSION_TO_FORMAT[extension]
  if (!format) {
    throw new Error(
      `Can't auto-detect a source format from "${filename}" (extension "${extension}"). ` +
        `Recognized: ${Object.keys(EXTENSION_TO_FORMAT).join(", ")}`
    )
  }
  return format
}
