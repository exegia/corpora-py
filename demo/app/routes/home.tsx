import { FileUploadProgressFill } from "@/components/upload"

export function meta() {
  return [{ title: "Corpora" }]
}

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6">
      <FileUploadProgressFill />
    </div>
  )
}
