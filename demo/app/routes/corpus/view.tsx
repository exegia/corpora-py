import { useState } from "react"
import { Form, useParams, useSearchParams } from "react-router"
import { Card } from "@astryxdesign/core/Card"
import { List, ListItem } from "@astryxdesign/core/List"
import { Text } from "@astryxdesign/core/Text"
import { TextInput } from "@astryxdesign/core/TextInput"
import { VStack } from "@astryxdesign/core/VStack"

export function meta() {
  return [{ title: "Corpus viewer · Corpora" }]
}

export default function CorpusView() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get("q") ?? "")

  return (
    <VStack gap={4} hAlign="stretch">
      {/* Search uses Form method="get" so the query lives in the URL. */}
      <Form method="get">
        <TextInput
          label={`Search ${id}`}
          htmlName="q"
          value={query}
          onChange={setQuery}
          placeholder={`Search ${id}…`}
          startIcon="search"
          hasClear
          isLabelHidden
        />
      </Form>

      <Card>
        <VStack gap={3} height="60vh">
          {/* TODO: render passages/results from a loader. */}
          <Text type="body" color="secondary">
            Viewer for corpus “{id}”. Text content will render here once data
            loading is wired up.
          </Text>
          <List density="compact">
            {Array.from({ length: 8 }).map((_, i) => (
              <ListItem
                key={i}
                label={`Placeholder passage ${i + 1}`}
                description="Sample text will appear here once the corpus loader is connected."
              />
            ))}
          </List>
        </VStack>
      </Card>
    </VStack>
  )
}
