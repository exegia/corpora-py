
import { BrowserWindow, Updater, Screen } from "electrobun/bun";
import { retrieve, store } from "./storage";
import { getAuth, end } from "./example-usage";

const DEV_SERVER_PORT = 5173;
const DEV_SERVER_URL = `http://localhost:${DEV_SERVER_PORT}`;

const primary = Screen.getPrimaryDisplay();
const windowWidth = 800;
const windowHeight = 600;

// Calculate centered position
const x = Math.round((primary.workArea.width - windowWidth) / 2) + primary.workArea.x;
const y = Math.round((primary.workArea.height - windowHeight) / 2) + primary.workArea.y;


// Check if Vite dev server is running for HMR
async function getMainViewUrl(): Promise<string> {
	const channel = await Updater.localInfo.channel();
	if (channel === "dev") {
		try {
			await fetch(DEV_SERVER_URL, { method: "HEAD" });
			console.log(`HMR enabled: Using Vite dev server at ${DEV_SERVER_URL}`);
			return DEV_SERVER_URL;
		} catch {
			console.log(
				"Vite dev server not running. Run 'bun run dev:hmr' for HMR support.",
			);
		}
	}
	return "views://mainview/index.html";
}

// Create the main application window
const url = await getMainViewUrl();

const mainWindow = new BrowserWindow({
	title: "CorporaPy testing",
  url,
  hidden: true,
  titleBarStyle: "hiddenInset",
  renderer: 'native',
  passthrough: true,
  frame: {
    width: windowWidth,
       height: windowHeight,
       x,
       y
  },
  styleMask: {
      // These are the current defaults
      Borderless: false,
      Titled: true,
      Closable: true,
      Miniaturizable: false,
      Resizable: false,
      UnifiedTitleAndToolbar: true,
      FullScreen: false,
      FullSizeContentView: false,
      UtilityWindow: false,
      DocModalWindow: false,
      NonactivatingPanel: true,
      HUDWindow: false,
    }
});

const start = async () => {
  try {
    const state = await retrieve();
    if (!state) {
      // This is probably the first time the app is being run, so no state yet.
      // We will create a new window and store it as the active window.
      mainWindow.show();
      store({ activeWindow: mainWindow, windows: [mainWindow.id], theme: "dark" });
      return;
    };
    if (state.activeWindow.id != mainWindow.id) {
      mainWindow.show();
    }

  } catch (error) {
    console.log(error);
  }
};

await start();
await getAuth();
