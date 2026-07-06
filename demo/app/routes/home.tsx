import { ClickableCard } from "@astryxdesign/core/ClickableCard"
import { Grid, GridSpan } from "@astryxdesign/core/Grid"
import { Heading, Text } from "@astryxdesign/core/Text"
import { VStack } from "@astryxdesign/core/VStack"
import {
  FilesUploadingIllustration,
  KeyPointsIllustration,
  OpenBookIllustration
} from "@/assets"
import type { ComponentType, SVGProps } from "react"

export function meta() {
  return [{ title: "Corpora" }]
}

interface MenuItem {
  label: string
  description: string
  href: string
  illustration: ComponentType<SVGProps<SVGSVGElement>>
}

const MENU_ITEMS: MenuItem[] = [
  {
    label: "Convert a corpus",
    description: "Turn a source document into a Text-Fabric dataset.",
    href: "/convert",
    illustration: FilesUploadingIllustration
  },
  {
    label: "Browse files",
    description: "View and download corpora that are ready to go.",
    href: "/files",
    illustration: OpenBookIllustration
  },
  {
    label: "Chat",
    description: "Ask questions and explore your corpora conversationally.",
    href: "/chat",
    illustration: KeyPointsIllustration
  }
]

export default function Home() {
  const [primary, ...rest] = MENU_ITEMS

  return (
    <VStack gap={6} hAlign="stretch" width="100%">
      <VStack gap={1}>
        <Heading level={2}>Welcome to Corpora</Heading>
        <Text type="body" color="secondary">
          Convert, browse, and chat with your Text-Fabric corpora.
        </Text>
      </VStack>
      <Grid columns={3} gap={5} width="100%">
        <GridSpan columns={2} rows={2}>
          <MenuCard item={primary} size="primary" />
        </GridSpan>
        {rest.map((item) => (
          <MenuCard key={item.href} item={item} size="secondary" />
        ))}
      </Grid>
    </VStack>
  )
}

function MenuCard({ item, size }: { item: MenuItem; size: "primary" | "secondary" }) {
  const Illustration = item.illustration
  const isPrimary = size === "primary"

  return (
    <ClickableCard label={item.label} height="100%" padding={10}>
      <VStack hAlign={isPrimary ? "start" : "stretch"} height="100%">
        <VStack gap={isPrimary ? 6 : 4} hAlign="stretch">
          <VStack height={isPrimary ? 268 : 96} hAlign={isPrimary ? "start" : "stretch"} vAlign="center">
            <Illustration className="h-full w-auto fill-neutral-800" />
          </VStack>
          <VStack gap={isPrimary ? 2 : 1}>
            <Heading level={2}>{item.label}</Heading>
            <Text className="text-md" color="secondary">
              {item.description}
            </Text>
          </VStack>
        </VStack>
        <Text type="label" color="accent" className="mt-4">
          Open →
        </Text>
      </VStack>
    </ClickableCard>
  )
}
