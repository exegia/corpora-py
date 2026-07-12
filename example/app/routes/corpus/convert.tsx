import { useEffect, useState } from "react"
import { type MetaDescriptor } from "react-router"
import { Card, CardContent } from "~/components/ui/card"
import { Badge } from "~/components/ui/badge"
import { Terminal1 } from "~/components/beste/block/terminal1"
import { Upload8 } from "~/components/beste/piece/upload8"
import { useUpload } from "~/lib/hooks/use-upload"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Convert | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" }
  ]
}

export default function CorpusConvert() {
  const [currentUploadId, setCurrentUploadId] = useState<string | null>(null)
  const { uploads, uploadFile, saveUpload } = useUpload()

  useEffect(() => {
    if (currentUploadId || Object.keys(uploads).length === 0) return
    const latest = Object.values(uploads).at(-1)
    if (latest) setCurrentUploadId(latest.id)
  }, [currentUploadId, uploads])

  const currentUpload = currentUploadId ? uploads[currentUploadId] : undefined
  const isBusy =
    currentUpload?.status === "uploading" ||
    currentUpload?.status === "queued" ||
    currentUpload?.status === "converting"

  const handleUpload = async (file: File) => {
    const id = await uploadFile(file, {
      name: file.name === "SBLGNT.zip" ? "SBLGNT" : undefined,
      description:
        file.name === "SBLGNT.zip"
          ? "Society of Biblical Literature Greek New Testament"
          : undefined,
      sourceFormat: "tf_zip"
    })
    setCurrentUploadId(id)
  }

  const statusLabel = currentUpload
    ? `${currentUpload.name}: ${currentUpload.status}`
    : undefined
  const terminalLogs = currentUpload
    ? [
      `Uploading ${currentUpload.name} to /convert`,
      ...(currentUpload.jobId ? [`Job ${currentUpload.jobId}`] : []),
      ...(currentUpload.logs ?? []),
      ...(currentUpload.error ? [`Error: ${currentUpload.error}`] : []),
      ...(currentUpload.status === "ready" ||
      currentUpload.status === "success"
        ? ["Archive is ready to download."]
        : [])
    ]
    : []

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">
          Convert to{" "}
          <Badge variant="secondary" className="py-1.5 text-xl">
            .corpus
          </Badge>
        </h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Import a Text-Fabric ZIP and package it as a Context-Fabric{" "}
          <code>.corpus</code> archive.
        </p>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 items-stretch gap-6">
          <Upload8
            title="SBLGNT Text-Fabric dataset"
            formats={["ZIP", "TF"]}
            limit="Sample included with the app"
            action="Upload SBLGNT.zip"
            accept=".zip,application/zip"
            disabled={isBusy}
            status={statusLabel}
            error={currentUpload?.error}
            onUpload={handleUpload}
            sample={{ name: "SBLGNT.zip", url: "/SBLGNT.zip" }}
            resultAction={
              currentUpload?.status === "ready"
                ? {
                  label: "Save .corpus",
                  onClick: () => saveUpload(currentUpload.id)
                }
                : undefined
            }
          />
          <Terminal1
            glowEffect={false}
            showCopyButton
            className="py-0"
            logs={terminalLogs}
            status={isBusy ? "Conversion in progress" : undefined}
            terminal={{ title: "Conversion API", commands: [] }}
          />
        </CardContent>
      </Card>
    </div>
  )
}
