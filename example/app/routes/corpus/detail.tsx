import { useNavigate, useParams } from "react-router"
import { Card, CardContent, CardFooter, CardHeader, CardTitle, CardDescription } from "~/components/ui/card"
import { Button } from "~/components/ui/button"

export function meta() {
  return [{ title: "Corpus detail · Corpora" }]
}

const META_ROWS = [
  { label: "Identifier", value: "—" },
  { label: "Format", value: "Text-Fabric" },
  { label: "Nodes", value: "—" },
  { label: "Features", value: "—" }
]

export default function CorpusDetail() {
  const { id } = useParams()
  const navigate = useNavigate()

  return (
    <div className="flex w-full flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Overview</CardTitle>
          <CardDescription>Metadata for corpus “{id}”.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y rounded-md border">
            {META_ROWS.map((row) => (
              <div key={row.label} className="grid grid-cols-3 items-center gap-2 px-4 py-2">
                <dt className="col-span-1 text-sm text-neutral-500">{row.label}</dt>
                <dd className="col-span-2 text-sm">{row.value}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
        <CardFooter className="justify-end">
          <Button onClick={() => navigate(`/corpus/${id}/view`)}>Open viewer</Button>
        </CardFooter>
      </Card>

      <p className="text-sm text-neutral-500">
        {/* TODO: load real corpus metadata via a loader. */}
        Detail content is a placeholder pending data wiring.
      </p>
    </div>
  )
}
