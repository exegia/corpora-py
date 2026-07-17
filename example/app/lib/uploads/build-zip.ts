/**
 * Minimal ZIP writer: entries are stored (method 0, no compression), which
 * is all the GitHub import needs -- the archive exists only to carry a
 * handful of fetched files into the same upload path as a user-dropped ZIP
 * (and `inspectZip`/`extractZipEntry` on the other side read stored entries
 * natively). Counterpart of inspect-zip.ts, which only ever *reads*.
 *
 * No ZIP64: callers cap total content size well below 4 GB.
 */

export type ZipFileInput = {
  /** Path inside the archive, forward-slash separated. */
  name: string
  data: Uint8Array<ArrayBuffer>
}

const CRC_TABLE = new Uint32Array(256).map((_, n) => {
  let c = n
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})

const crc32 = (data: Uint8Array): number => {
  let crc = 0xffffffff
  for (const byte of data) crc = CRC_TABLE[(crc ^ byte) & 0xff]! ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

/** MS-DOS date/time pair as used in ZIP headers, from a JS Date. */
const dosDateTime = (date: Date): { time: number; date: number } => ({
  time:
    (date.getHours() << 11) |
    (date.getMinutes() << 5) |
    Math.floor(date.getSeconds() / 2),
  date:
    ((Math.max(date.getFullYear(), 1980) - 1980) << 9) |
    ((date.getMonth() + 1) << 5) |
    date.getDate()
})

export function buildStoredZip(files: ZipFileInput[]): Blob {
  const encoder = new TextEncoder()
  const now = dosDateTime(new Date())
  const chunks: Uint8Array<ArrayBuffer>[] = []
  const central: Uint8Array<ArrayBuffer>[] = []
  let offset = 0

  for (const file of files) {
    const name = encoder.encode(file.name) as Uint8Array<ArrayBuffer>
    const crc = crc32(file.data)

    const local = new DataView(new ArrayBuffer(30))
    local.setUint32(0, 0x04034b50, true) // local file header signature
    local.setUint16(4, 20, true) // version needed
    local.setUint16(8, 0, true) // method: stored
    local.setUint16(10, now.time, true)
    local.setUint16(12, now.date, true)
    local.setUint32(14, crc, true)
    local.setUint32(18, file.data.length, true) // compressed size
    local.setUint32(22, file.data.length, true) // uncompressed size
    local.setUint16(26, name.length, true)
    chunks.push(new Uint8Array(local.buffer), name, file.data)

    const dir = new DataView(new ArrayBuffer(46))
    dir.setUint32(0, 0x02014b50, true) // central directory signature
    dir.setUint16(4, 20, true) // version made by
    dir.setUint16(6, 20, true) // version needed
    dir.setUint16(10, 0, true) // method: stored
    dir.setUint16(12, now.time, true)
    dir.setUint16(14, now.date, true)
    dir.setUint32(16, crc, true)
    dir.setUint32(20, file.data.length, true)
    dir.setUint32(24, file.data.length, true)
    dir.setUint16(28, name.length, true)
    dir.setUint32(42, offset, true) // local header offset
    central.push(new Uint8Array(dir.buffer), name)

    offset += 30 + name.length + file.data.length
  }

  const centralSize = central.reduce((size, part) => size + part.length, 0)
  const eocd = new DataView(new ArrayBuffer(22))
  eocd.setUint32(0, 0x06054b50, true) // end of central directory signature
  eocd.setUint16(8, files.length, true) // entries on this disk
  eocd.setUint16(10, files.length, true) // total entries
  eocd.setUint32(12, centralSize, true)
  eocd.setUint32(16, offset, true) // central directory offset

  return new Blob([...chunks, ...central, new Uint8Array(eocd.buffer)], {
    type: "application/zip"
  })
}
