import { useState } from "react"
import { Form } from "react-router"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "~/components/ui/card"
import { Button } from "~/components/ui/button"
import { Input } from "~/components/ui/input"
import { Textarea } from "~/components/ui/textarea"

export function meta() {
  return [{ title: "Upload corpus · Corpora" }]
}

export default function CorpusUpload() {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [file, setFile] = useState<File | null>(null)

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">Upload corpus</h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Add an existing Text-Fabric dataset to your library.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Upload</CardTitle>
          <CardDescription>
            Provide details and select the dataset archive.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* TODO: wire an `action` to receive the upload (multipart). */}
          <Form
            method="post"
            encType="multipart/form-data"
            className="space-y-4"
          >
            <div className="space-y-1">
              <label htmlFor="name" className="block text-sm font-medium">
                Corpus name
              </label>
              <Input
                aria-label="name"
                id="name"
                name="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. BHSA"
                required
              />
              <p className="text-xs text-neutral-500">
                A short, unique identifier for the corpus.
              </p>
            </div>

            <div className="space-y-1">
              <label
                htmlFor="description"
                className="block text-sm font-medium"
              >
                Description
              </label>
              <Textarea
                aria-label="description"
                id="description"
                name="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this corpus contain?"
                rows={3}
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="archive" className="block text-sm font-medium">
                Dataset archive
              </label>
              <input
                id="archive"
                name="archive"
                type="file"
                accept=".zip,.tar,.gz,.tgz"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-neutral-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-neutral-200 dark:file:bg-neutral-800 dark:hover:file:bg-neutral-700"
                required
              />
              <p className="text-xs text-neutral-500">
                ZIP or tarball containing the Text-Fabric dataset.
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button type="reset" variant="ghost">
                Reset
              </Button>
              <Button type="submit">Upload</Button>
            </div>
          </Form>
        </CardContent>
      </Card>
    </div>
  )
}
