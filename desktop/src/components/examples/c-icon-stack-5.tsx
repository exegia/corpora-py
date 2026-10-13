import { Files, Plus } from "lucide-react"
import { IconStack } from "@/components/reui/icon-stack"
import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"

export function ConversionJobsEmpty({ onCreate, compact = false }: { onCreate: () => void; compact?: boolean }) {
    return (
        <Empty className={compact ? "gap-4 px-3 py-8" : "min-h-80 px-6 py-12"}>
            <EmptyHeader>
                <EmptyMedia>
                    <IconStack
                        aria-hidden="true"
                        className="text-primary">
                        <Files
                            className="size-5 text-primary"
                            strokeWidth={1.5}
                        />
                    </IconStack>
                </EmptyMedia>
                <EmptyTitle className="text-base">Your next corpus starts here</EmptyTitle>
                <EmptyDescription className="text-xs leading-relaxed">
                    Convert a document or source dataset, follow its real pipeline, then download the result. Create a
                    conversion to see its status and logs here.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    type="button"
                    variant="outline"
                    onClick={onCreate}>
                    <Plus aria-hidden="true" />
                    New conversion
                </Button>
            </EmptyContent>
        </Empty>
    )
}
