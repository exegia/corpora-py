import { useState } from "react"
import { Form } from "react-router"
import { Button } from "@astryxdesign/core/Button"
import { Card } from "@astryxdesign/core/Card"
import { FileInput } from "@astryxdesign/core/FileInput"
import { FormLayout } from "@astryxdesign/core/FormLayout"
import { HStack } from "@astryxdesign/core/HStack"
import { Heading, Text } from "@astryxdesign/core/Text"
import { TextArea } from "@astryxdesign/core/TextArea"
import { TextInput } from "@astryxdesign/core/TextInput"
import { VStack } from "@astryxdesign/core/VStack"

export function meta() {
  return [{ title: "Upload corpus · Corpora" }]
}

export default function CorpusUpload() {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [file, setFile] = useState<File | null>(null)

  return (
    <VStack gap={6} hAlign="stretch">
      <VStack gap={1}>
        <Heading level={2}>Upload corpus</Heading>
        <Text type="body" color="secondary">
          Add an existing Text-Fabric dataset to your library.
        </Text>
      </VStack>

      <Card>
        {/* TODO: wire an `action` to receive the upload (multipart). */}
        <Form method="post" encType="multipart/form-data">
          <FormLayout>
            <TextInput
              label="Corpus name"
              htmlName="name"
              value={name}
              onChange={setName}
              placeholder="e.g. BHSA"
              description="A short, unique identifier for the corpus."
              isRequired
            />

            <TextArea
              label="Description"
              htmlName="description"
              value={description}
              onChange={setDescription}
              placeholder="What does this corpus contain?"
              rows={3}
              isOptional
            />

            <FileInput
              label="Dataset archive"
              value={file}
              onChange={(files) => setFile(Array.isArray(files) ? files[0] ?? null : files)}
              accept=".zip,.tar,.gz,.tgz"
              description="ZIP or tarball containing the Text-Fabric dataset."
              isRequired
            />

            <HStack gap={2} hAlign="end">
              <Button label="Reset" type="reset" variant="ghost" />
              <Button label="Upload" type="submit" variant="primary" />
            </HStack>
          </FormLayout>
        </Form>
      </Card>
    </VStack>
  )
}
