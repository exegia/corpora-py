import { useState } from "react"
import { type MetaDescriptor } from "react-router"
import { Card, CardContent } from "~/components/ui/card"
import { Badge } from "~/components/ui/badge"
import { Terminal1 } from "~/components/beste/block/terminal1"
import { Upload8 } from "~/components/beste/piece/upload8"
import { useUpload } from "~/lib/hooks/use-upload"
import { cn } from "~/lib/utils"

export function meta(): MetaDescriptor[] {
  return [
    { title: "Convert | Corpora" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" }
  ]
}

export default function CorpusConvert() {
  const [currentUploadId, setCurrentUploadId] = useState<string | null>(null)
  const [showTerminal, setShowTerminal] = useState(false)
  const { uploads, uploadFile, saveUpload } = useUpload()

  const currentUpload = currentUploadId ? uploads[currentUploadId] : undefined
  const isBusy =
    currentUpload?.status === "uploading" ||
    currentUpload?.status === "queued" ||
    currentUpload?.status === "converting"

  const handleUpload = async (file: File) => {
    setCurrentUploadId(null)
    setShowTerminal(true)
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
        <CardContent
          className={cn(
            "grid grid-cols-1 items-stretch gap-6",
            showTerminal && "lg:grid-cols-2"
          )}
        >
          <Upload8
            formats={[".zip", ".tf", ".pdf", ".txt", ".xml", ".tei"]}
            limit="Sample included with the app"
            action="Upload"
            accept=".zip,application/zip"
            disabled={isBusy}
            status={statusLabel}
            error={currentUpload?.error}
            onUpload={handleUpload}
            resultAction={
              currentUpload?.status === "ready"
                ? {
                  label: "Save .corpus",
                  onClick: () => saveUpload(currentUpload.id)
                }
                : undefined
            }
          />
          {showTerminal && (
            <section className="animate-in duration-500 fade-in slide-in-from-bottom-3 motion-reduce:animate-none">
              <Terminal1
                glowEffect={false}
                showCopyButton
                className="py-0"
                logs={terminalLogs}
                progress={currentUpload?.progress}
                status={isBusy ? "Conversion in progress" : "Preparing upload"}
                isRunning={!currentUpload || isBusy}
                terminal={{ title: "Conversion API", commands: [] }}
              />
            </section>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
