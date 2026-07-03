import { useNavigate } from "react-router"
import { FileUploadProgressFill } from "@/components/upload"
import { useWebSocket } from "@/hooks"
import { useEffect } from "react"

export function meta() {
  return [{ title: "Corpora" }]
}
export default function Home() {
  const navigate = useNavigate()
  const { connect } = useWebSocket()

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6">
      <FileUploadProgressFill />
    </div>
  )
}
