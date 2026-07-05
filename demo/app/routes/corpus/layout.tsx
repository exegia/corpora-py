import { Outlet, useLocation, useParams } from "react-router"
import { Badge } from "@astryxdesign/core/Badge"
import { BreadcrumbItem, Breadcrumbs } from "@astryxdesign/core/Breadcrumbs"
import { HStack } from "@astryxdesign/core/HStack"
import { Heading } from "@astryxdesign/core/Text"
import { Tab, TabList } from "@astryxdesign/core/TabList"
import { VStack } from "@astryxdesign/core/VStack"

export default function CorpusLayout() {
  const { id } = useParams()
  const { pathname } = useLocation()
  const activeTab = pathname.endsWith("/view") ? "view" : "detail"

  return (
    <VStack gap={6} width="100%" hAlign="stretch">
      <Breadcrumbs>
        <BreadcrumbItem href="/">Home</BreadcrumbItem>
        <BreadcrumbItem href="/">Corpus</BreadcrumbItem>
        <BreadcrumbItem isCurrent>{id}</BreadcrumbItem>
      </Breadcrumbs>

      <HStack gap={3} hAlign="center">
        <Heading level={2}>{id}</Heading>
        <Badge variant="neutral" label="corpus" />
      </HStack>

      <TabList value={activeTab} onChange={() => {
      }} hasDivider>
        <Tab value="detail" label="Detail" href={`/corpus/${id}`} />
        <Tab value="view" label="View" href={`/corpus/${id}/view`} />
      </TabList>

      <Outlet />
    </VStack>
  )
}
