import { useState } from "react"
import { Form } from "react-router"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "~/components/ui/card"
import { Button } from "~/components/ui/button"
import { Input } from "~/components/ui/input"

export function meta() {
  return [{ title: "Convert source · Corpora" }]
}

const SOURCE_FORMATS = [
  { value: "epub", label: "EPUB" },
  { value: "html", label: "HTML" }
]

export default function CorpusConvert() {
  const [name, setName] = useState("")
  const [format, setFormat] = useState("epub")
  const [source, setSource] = useState<File | null>(null)

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">Convert to .corpus</h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Convert an EPUB or HTML document into a Text-Fabric dataset.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Conversion</CardTitle>
          <CardDescription>Choose a format, name the corpus, and upload the source file.</CardDescription>
        </CardHeader>
        <CardContent>
          {/* TODO: wire an `action` to kick off the conversion pipeline. */}
          <Form method="post" encType="multipart/form-data" className="space-y-4">
            <div className="space-y-1">
              <label htmlFor="name" className="block text-sm font-medium">Corpus name</label>
              <Input aria-label="Corpus name" id="name" name="name" value={name}
                     onChange={(e) => setName(e.target.value)}
                     placeholder="e.g. my-book" required />
              <p className="text-xs text-neutral-500">Name for the generated dataset.</p>
            </div>

            <div className="space-y-1">
              <label htmlFor="format" className="block text-sm font-medium">Source format</label>
              <select
                id="format"
                name="format"
                value={format}
                onChange={(e) => setFormat(e.target.value)}
                className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-neutral-700"
                required
              >
                {SOURCE_FORMATS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label htmlFor="source" className="block text-sm font-medium">Source file</label>
              <input
                id="source"
                name="source"
                type="file"
                accept=".epub,.html,.htm"
                onChange={(e) => setSource(e.target.files?.[0] ?? null)}
                className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-neutral-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-neutral-200 dark:file:bg-neutral-800 dark:hover:file:bg-neutral-700"
                required
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button type="reset" variant="ghost">Reset</Button>
              <Button type="submit">Convert</Button>
            </div>
          </Form>
        </CardContent>
      </Card>
    </div>
  )
}
