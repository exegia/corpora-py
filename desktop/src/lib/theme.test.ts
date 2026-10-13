import { describe, expect, test } from "bun:test"
import { nextTheme, parseTheme, resolveTheme } from "../hooks/use-theme"

describe("theme preference", () => {
    test("accepts each supported preference", () => {
        for (const theme of ["system", "light", "dark"] as const) {
            expect(parseTheme(theme)).toBe(theme)
        }
    })

    test("defaults absent or invalid persisted values to system", () => {
        for (const value of [null, undefined, "", "DARK", "auto", {}, 0]) {
            expect(parseTheme(value)).toBe("system")
        }
    })

    test("cycles system → light → dark → system", () => {
        expect(nextTheme("system")).toBe("light")
        expect(nextTheme("light")).toBe("dark")
        expect(nextTheme("dark")).toBe("system")
    })

    test("system mode follows OS appearance", () => {
        expect(resolveTheme("system", false)).toBe("light")
        expect(resolveTheme("system", true)).toBe("dark")
    })

    test("explicit modes ignore OS appearance", () => {
        for (const systemDark of [false, true]) {
            expect(resolveTheme("light", systemDark)).toBe("light")
            expect(resolveTheme("dark", systemDark)).toBe("dark")
        }
    })
})
