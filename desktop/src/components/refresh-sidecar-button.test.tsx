import { describe, expect, test } from "bun:test"
import { renderToStaticMarkup } from "react-dom/server"
import { RefreshSidecarButton } from "./refresh-sidecar-button"
import Logo from "./logo"

const onRefresh = () => {}

describe("sidecar check control", () => {
    test("renders an idle check button", () => {
        const markup = renderToStaticMarkup(<RefreshSidecarButton isChecking={false} onRefresh={onRefresh} />)
        expect(markup).toContain('type="button"')
        expect(markup).toContain("Check sidecar")
        expect(markup).toContain('aria-busy="false"')
        expect(markup).not.toContain('disabled=""')
    })

    test("disables the control and announces its loading state", () => {
        const markup = renderToStaticMarkup(<RefreshSidecarButton isChecking onRefresh={onRefresh} />)
        expect(markup).toContain('disabled=""')
        expect(markup).toContain('aria-busy="true"')
        expect(markup).toContain('data-state="loading"')
        expect(markup).toContain("Checking sidecar…")
    })

    test("keeps a descriptive accessible name in the compact footer", () => {
        const markup = renderToStaticMarkup(<RefreshSidecarButton compact isChecking={false} onRefresh={onRefresh} />)
        expect(markup).toContain('aria-label="Check sidecar now"')
        expect(markup).toContain('data-size="xs"')
    })
})

describe("desktop logo", () => {
    test("inherits theme color and forwards SVG accessibility props", () => {
        const markup = renderToStaticMarkup(<Logo className="size-6 text-primary" aria-hidden="true" focusable="false" />)
        expect(markup).toContain('viewBox="0 0 1081 1083"')
        expect(markup).toContain('fill="currentColor"')
        expect(markup).not.toContain('fill="current"')
        expect(markup).toContain('aria-hidden="true"')
        expect(markup).toContain('focusable="false"')
        expect(markup).toContain('class="size-6 text-primary"')
    })
})
