import { useState } from "react"
import { Form } from "react-router"
import { Button } from "@astryxdesign/core/Button"
import { Card } from "@astryxdesign/core/Card"
import { FileInput } from "@astryxdesign/core/FileInput"
import { FormLayout } from "@astryxdesign/core/FormLayout"
import { HStack } from "@astryxdesign/core/HStack"
import { Heading, Text } from "@astryxdesign/core/Text"
import { Selector } from "@astryxdesign/core/Selector"
import { TextInput } from "@astryxdesign/core/TextInput"
import { VStack } from "@astryxdesign/core/VStack"

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
    <VStack gap={6} hAlign="stretch">
      <VStack gap={1}>
        <Heading level={2}>Convert source</Heading>
        <Text type="body" color="secondary">
          Convert an EPUB or HTML document into a Text-Fabric dataset.
        </Text>
      </VStack>

      <Card>
        {/* TODO: wire an `action` to kick off the conversion pipeline. */}
        <Form method="post" encType="multipart/form-data">
          <FormLayout>
            <TextInput
              label="Corpus name"
              htmlName="name"
              value={name}
              onChange={setName}
              placeholder="e.g. my-book"
              description="Name for the generated dataset."
              isRequired
            />

            <Selector
              label="Source format"
              options={SOURCE_FORMATS}
              value={format}
              onChange={setFormat}
              isRequired
            />
            <input type="hidden" name="format" value={format} />

            <FileInput
              label="Source file"
              value={source}
              onChange={(files) => setSource(Array.isArray(files) ? files[0] ?? null : files)}
              accept=".epub,.html,.htm"
              isRequired
            />

            <HStack gap={2} hAlign="end">
              <Button label="Reset" type="reset" variant="ghost" />
              <Button label="Convert" type="submit" variant="primary" />
            </HStack>
          </FormLayout>
        </Form>
      </Card>
    </VStack>
  )
}
