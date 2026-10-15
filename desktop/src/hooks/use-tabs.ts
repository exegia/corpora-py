import { useAtomValue, useSetAtom } from "jotai"
import { workspaceActionAtom, workspaceAtom } from "@/shared/store"

export const useTabs = () => {
    const workspace = useAtomValue(workspaceAtom)
    const dispatch = useSetAtom(workspaceActionAtom)
    return { workspace, dispatch }
}
