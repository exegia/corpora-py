import { expect, test } from "bun:test"
import { DESKTOP_DEFAULT_FRAME, DESKTOP_MIN_WIDTH, enforceMinimumWindowWidth } from "./window-layout"

test("native resizing keeps enough width for the sidebar and workspace", () => {
    let width = 900
    let height = 700
    let fullscreen = false
    let resize = (_event: unknown) => {}
    const calls: number[][] = []
    enforceMinimumWindowWidth({
        on(name, handler) { expect(name).toBe("resize"); resize = handler },
        getSize: () => ({ width, height }),
        isFullScreen: () => fullscreen,
        setSize(nextWidth, nextHeight) {
            calls.push([nextWidth, nextHeight])
            width = nextWidth
            height = nextHeight
        }
    })
    expect(DESKTOP_DEFAULT_FRAME.width).toBeGreaterThanOrEqual(DESKTOP_MIN_WIDTH)
    resize(undefined)
    expect(calls).toEqual([[1024, 700]])
    resize(undefined)
    expect(calls).toHaveLength(1)
    width = 1400
    resize(undefined)
    expect(calls).toHaveLength(1)
    width = 900
    fullscreen = true
    resize(undefined)
    expect(calls).toHaveLength(1)
})
