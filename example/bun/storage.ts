import { Utils } from "electrobun/bun"
import { join } from "path"
import Bun from "bun"
import type { WindowState } from "~/lib/types"


const settingsPath = join(Utils.paths.userData, "state.json")
const retrieve = async (): Promise<WindowState | null> => {
  // Restore state from disk
  try {
    const stateFileBlob = Bun.file(settingsPath, { type: "application/json" })
    const exist = await stateFileBlob.exists()
    if (!exist) return null
    const stateFileContent = await stateFileBlob.json()
    return stateFileContent as WindowState
  } catch (error) {
    console.log(error)
  }
  return null
}

const store = async (state: WindowState) => {
  try {
    // Write a settings file
    await Bun.write(settingsPath, JSON.stringify(state))
  } catch (error) {
    console.log(error)
  }
}

export { store, retrieve }
