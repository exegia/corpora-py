import { BrowserViewOptions, BrowserWindow, Screen } from "electrobun";


class WindowManager {


  primaryScreen = Screen.getPrimaryDisplay();
  private windowWidth = 800;
  private windowHeight = 600;

  get x()  {
    return Math.round((this.primaryScreen.workArea.width - this.windowWidth) / 2 + this.primaryScreen.workArea.x)
  }

  get y()  {
    return Math.round((this.primaryScreen.workArea.height - this.windowHeight) / 2 + this.primaryScreen.workArea.y)
  }
  private current?: BrowserWindow;
  private styleMask = {
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
    NonactivatingPanel: false,
    HUDWindow: false,
  };
  private config: Partial<BrowserViewOptions> = {
    sandbox: false,
    frame: {
      width: this.windowWidth,
      height: this.windowHeight,
      x: this.x,
      y: this.y
    }
  }

  private _mainWindow: BrowserWindow = new BrowserWindow({
    ...this.config,
    title: "Demo Corpora: Main Title",
    hidden: true,
    passthrough: true,
    styleMask: this.styleMask,
    renderer: 'native',
    titleBarStyle: 'hiddenInset'
  })

  public loadWindow = (id: TWindowID, url: string): BrowserWindow | undefined => {
    const _window = this.windows[id];
    _window.webview.loadURL(url);
    this.windowWidth = this.windowWidth * 1.3;
    this.windowHeight = this.windowHeight * 1.3;
    this.current = _window;
    return _window;
  }

  get mainWindowId(): string {
    const id = this._mainWindow.id;
    return `window_${id}`;
  }

  private windows: Record<string, BrowserWindow> = {
    [this.mainWindowId]: this._mainWindow
  }

  public close = (id: TWindowID) => {
    this.windows[id].close();
}

  public open = (id: TWindowID) => {
    // if current view is already set, check if the id is already loaded.
    if (this.current) {
      const currentId = `window_${this.current.id}`;
      // If the passed id differs, we can pass safely load the new view.
      if (currentId === id) throw new Error(`Window ${id} is already open`);
        // close the previous window,
        this.close(currentId);
    }
    // open new window.
    this.windows[id].show();
    this.current = this.windows[id];
  }

}

const windowManager = new WindowManager();
export type TWindowID = typeof windowManager.mainWindowId;
export {
  windowManager
}
