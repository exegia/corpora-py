import { useState } from "react"
import { Form, type MetaDescriptor } from "react-router"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "~/components/ui/card"
import { Button } from "~/components/ui/button"
import { Input } from "~/components/ui/input"
import { Badge } from "~/components/ui/badge"
import { CFileUpload } from "~/components/examples/c-file-upload-5"
import { Terminal1 } from "~/components/beste/block/terminal1"

export function meta(): MetaDescriptor[] {
  return [{ title: "Convert | Corpora" }, { tagName: "link", rel: "icon", href: "/favicon.ico" }]
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
        <h2 className="text-2xl font-semibold">Convert to <Badge variant="secondary"
                                                                 className="text-xl py-1.5">.corpus</Badge>
        </h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Convert an EPUB or HTML document into a Text-Fabric dataset.
        </p>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2">
          <CFileUpload />
          <Terminal1 glowEffect={false} />
        </CardContent>
      </Card>
    </div>
  )
}
