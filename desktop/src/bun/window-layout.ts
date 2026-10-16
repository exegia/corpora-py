export const DESKTOP_MIN_WIDTH = 1024
export const DESKTOP_DEFAULT_FRAME = { width: 1200, height: 760 }

interface SizedWindow {
    on(name: string, handler: (event: unknown) => void): void
    getSize(): { width: number; height: number }
    isFullScreen(): boolean
    setSize(width: number, height: number): unknown
}

// The pinned SDK has no minimum-size setter. Constrain its native resize event.
export function enforceMinimumWindowWidth(window: SizedWindow) {
    window.on("resize", () => {
        const { width, height } = window.getSize()
        if (width < DESKTOP_MIN_WIDTH && !window.isFullScreen()) {
            window.setSize(DESKTOP_MIN_WIDTH, height)
        }
    })
}
