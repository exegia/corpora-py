import { describe, expect, test } from "bun:test"
import { renderToStaticMarkup } from "react-dom/server"
import { formatBytes, validateUploadFile } from "@/hooks/use-file-upload"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Field, FieldHelper, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { ConversionReviewSteps } from "./c-stepper-20"

const limit = 100 * 1024 * 1024

describe("conversion source selection", () => {
    test("accepts supported uppercase extensions and empty MIME types", () => {
        expect(
            validateUploadFile(
                { name: "BOOK.EPUB", type: "", size: 256 },
                { accept: ".epub,.pdf,.xml,.tei,.txt,.zip", maxSize: limit }
            )
        ).toBeNull()
    })
    test("accepts the boundary and rejects an oversized source", () => {
        expect(
            validateUploadFile({ name: "book.pdf", type: "application/pdf", size: limit }, { maxSize: limit })
        ).toBeNull()
        expect(
            validateUploadFile({ name: "book.pdf", type: "application/pdf", size: limit + 1 }, { maxSize: limit })
        ).toContain("100 MiB")
    })
    test("rejects an empty source and unsupported extension", () => {
        expect(validateUploadFile({ name: "empty.txt", size: 0, type: "text/plain" }, { accept: ".txt" })).toContain(
            "empty"
        )
        expect(validateUploadFile({ name: "book.exe", size: 100, type: "" }, { accept: ".txt,.pdf" })).toContain(
            "not a supported source"
        )
    })
    test("matches compound archive extensions and MIME wildcards", () => {
        expect(validateUploadFile({ name: "edition.tei.zip", type: "", size: 100 }, { accept: ".tei.zip" })).toBeNull()
        expect(
            validateUploadFile({ name: "image.png", type: "image/png", size: 100 }, { accept: "image/*" })
        ).toBeNull()
        expect(validateUploadFile({ name: "nottei.zip", type: "", size: 100 }, { accept: ".tei.zip" })).not.toBeNull()
    })
    test("formats truthful binary sizes", () => {
        expect(formatBytes(limit)).toBe("100 MiB")
        expect(formatBytes(0)).toBe("0 B")
        expect(formatBytes(Infinity)).toBe("unlimited")
    })
})

describe("installed Ark primitive integration", () => {
    test("keeps one radio label and an accessible hidden input", () => {
        const markup = renderToStaticMarkup(
            <RadioGroup
                aria-label="Output format"
                value="corpus">
                <RadioGroupItem value="corpus">Corpus</RadioGroupItem>
                <RadioGroupItem
                    value="cusx"
                    disabled>
                    CUSX
                </RadioGroupItem>
            </RadioGroup>
        )
        expect(markup).toContain('role="radiogroup"')
        expect(markup).toContain('aria-label="Output format"')
        expect(markup).toContain('type="radio"')
        expect(markup).toContain('checked=""')
        expect(markup.match(/<label /g)?.length).toBe(2)
        expect(markup).toContain('disabled=""')
    })
    test("renders one real toggle button per log-level item", () => {
        const markup = renderToStaticMarkup(
            <ToggleGroup
                multiple
                value={["info"]}
                aria-label="Log levels">
                <ToggleGroupItem value="info">Info</ToggleGroupItem>
                <ToggleGroupItem value="error">Error</ToggleGroupItem>
            </ToggleGroup>
        )
        expect(markup.match(/<button /g)?.length).toBe(2)
        expect(markup).toContain('aria-pressed="true"')
        expect(markup).toContain('aria-pressed="false"')
        expect(markup).toContain('type="button"')
    })
    test("renders field labels, helpers and invalid input semantics", () => {
        const markup = renderToStaticMarkup(
            <Field
                required
                invalid>
                <FieldLabel>Corpus name</FieldLabel>
                <Input
                    value=""
                    readOnly
                />
                <FieldHelper>Name the corpus</FieldHelper>
            </Field>
        )
        expect(markup).toContain('aria-invalid="true"')
        expect(markup).toContain('data-part="helper-text"')
        expect(markup).toContain("for=")
    })
    test("does not let the review rail skip incomplete source validation", () => {
        const markup = renderToStaticMarkup(
            <ConversionReviewSteps
                current={0}
                reachable={0}
                onChange={() => {}}
            />
        )
        expect(markup.match(/disabled=""/g)?.length).toBe(2)
        expect(markup).toContain('aria-current="step"')
        expect(markup).toContain('aria-label="New conversion steps"')
    })
})
