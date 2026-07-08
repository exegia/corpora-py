import { useState } from "react"
import { Form, useParams, useSearchParams } from "react-router"
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card"
import { Input } from "~/components/ui/input"

export function meta() {
  return [{ title: "Corpus viewer · Corpora" }]
}

export default function CorpusView() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get("q") ?? "")

  return (
    <div className="flex w-full flex-col gap-4">
      {/* Search uses Form method="get" so the query lives in the URL. */}
      <Form method="get" className="w-full">
        <label htmlFor="q" className="sr-only">{`Search ${id}`}</label>
        <Input id="q" name="q" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Search ${id}…`} />
      </Form>

      <Card>
        <CardHeader>
          <CardTitle>Viewer</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* TODO: render passages/results from a loader. */}
          <p className="text-sm text-neutral-500">
            Viewer for corpus “{id}”. Text content will render here once data loading is wired up.
          </p>
          <ul className="divide-y rounded-md border text-sm">
            {Array.from({ length: 8 }).map((_, i) => (
              <li key={i} className="px-4 py-2">
                <div className="font-medium">{`Placeholder passage ${i + 1}`}</div>
                <div className="text-neutral-500">Sample text will appear here once the corpus loader is connected.
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
