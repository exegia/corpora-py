import { FileUploadProgressFill as FileUploadProgress } from "@/components/upload"

export function meta() {
  return [{ title: "Corpora" }]
}

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6">
      <FileUploadProgress />
    </div>
  )
}
