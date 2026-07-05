import { useNavigate, useParams } from "react-router"
import { Button } from "@astryxdesign/core/Button"
import { Card } from "@astryxdesign/core/Card"
import {
  Layout,
  LayoutContent,
  LayoutFooter,
  LayoutHeader
} from "@astryxdesign/core/Layout"
import { List, ListItem } from "@astryxdesign/core/List"
import { Heading, Text } from "@astryxdesign/core/Text"
import { VStack } from "@astryxdesign/core/VStack"

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
    <VStack gap={6} hAlign="stretch">
      <Card>
        <Layout
          header={
            <LayoutHeader hasDivider>
              <VStack gap={1}>
                <Heading level={4}>Overview</Heading>
                <Text type="body" color="secondary">
                  Metadata for corpus “{id}”.
                </Text>
              </VStack>
            </LayoutHeader>
          }
          content={
            <LayoutContent isScrollable={false}>
              <List hasDividers density="compact">
                {META_ROWS.map((row) => (
                  <ListItem
                    key={row.label}
                    label={row.label}
                    description={row.value}
                  />
                ))}
              </List>
            </LayoutContent>
          }
          footer={
            <LayoutFooter hasDivider>
              <Button
                label="Open viewer"
                variant="primary"
                onClick={() => navigate(`/corpus/${id}/view`)}
              />
            </LayoutFooter>
          }
        />
      </Card>

      <Text type="body" color="secondary">
        {/* TODO: load real corpus metadata via a loader. */}
        Detail content is a placeholder pending data wiring.
      </Text>
    </VStack>
  )
}
