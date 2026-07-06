import { FileUploadProgressFill as FileUploadProgress } from "@/components/upload"
import { HStack } from "@astryxdesign/core/HStack"

export function meta() {
  return [{ title: "Corpora" }]
}

export default function Home() {
  return (
    <HStack gap={6} width={"100%"} hAlign={"center"}>
      <FileUploadProgress />
    </HStack>
  )
}
