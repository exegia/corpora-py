import { Updater, Utils } from "electrobun/bun"
import { windowManager } from "./windows"
import { connect } from "./websocket"

const DEV_SERVER_PORT = 5173
const DEV_SERVER_URL = `http://localhost:${DEV_SERVER_PORT}`

// Check if Vite dev server is running for HMR
async function getMainViewUrl(): Promise<string> {
  const channel = await Updater.localInfo.channel()
  if (channel === "dev") {
    try {
      await fetch(DEV_SERVER_URL, { method: "HEAD" })
      console.log(`HMR enabled: Using Vite dev server at ${DEV_SERVER_URL}`)
      return DEV_SERVER_URL
    } catch {
      console.log(
        "Vite dev server not running. Run 'bun run dev:hmr' for HMR support."
      )
    }
  }
  return "views://mainview/index.html"
}

// Create the main application window


const start = async () => {

  const url = await getMainViewUrl()
  console.log("Loading view into window..")
  const main = windowManager.loadWindow(windowManager.mainWindowId, url)
  if (!main) {
    const { response } = await Utils.showMessageBox({
      type: "error",
      message: `Main window could not load the dom: ${url}`,
      buttons: ["Ok, thanks"]
    })
    if (response >= 0) windowManager.close(windowManager.mainWindowId)
    return
  }
  console.log("Opening window now..")
  main.show()

  // Connect the socket server once the window is showing.

  if (main.state == "creating") await connect.start()
  console.log("WINDOW STATE:", main.state)

  main.on("close", () => {
    void connect.close()
  })
}

await start()
