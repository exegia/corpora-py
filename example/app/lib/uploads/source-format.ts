// Mirrors `_EXTENSION_TO_FORMAT` in packages/admin/src/admin/services/api.py's
// `SourceFormat` enum values -- `POST /convert`'s `source_format` field is
// required (there's no server-side auto-detection), so the UI has to supply
// one. `.xml` maps to "tei" rather than the generic "xml" on purpose: XML has
// no Text-Fabric converter yet (see packages/admin/CLAUDE.md's "Known gaps"),
// TEI documents are almost always authored with a plain `.xml` extension,
// and TEI is the only working converter a bare `.xml` file could plausibly
// mean.
export const EXTENSION_TO_FORMAT: Record<string, string> = {
  ".epub": "epub",
  ".html": "html",
  ".xml": "tei",
  ".tei": "tei",
  ".pdf": "pdf",
  ".txt": "plain",
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
