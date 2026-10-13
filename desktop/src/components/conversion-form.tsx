import { useCallback, useRef, useState, type FormEvent } from "react"
import { ArrowLeft, ArrowRight, FileCheck2, LoaderCircle, ShieldCheck } from "lucide-react"
import { ConversionSourceAttachment } from "@/components/examples/c-attachment-6"
import { SupportedConversionSources } from "@/components/examples/c-file-type-4"
import { ConversionReviewSteps, type ConversionReviewStep } from "@/components/examples/c-stepper-20"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldError, FieldGroup, FieldHelper, FieldLabel, FieldLegend, FieldRequiredIndicator, FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Textarea } from "@/components/ui/textarea"
import { useFileUpload, validateUploadFile, type FileWithPreview } from "@/hooks/use-file-upload"
import { SOURCE_FORMATS, OUTPUT_FORMATS, MAX_UPLOAD_BYTES, formatBytes, inferSourceFormat } from "@/lib/conversion"
import type { ConversionJob, ConversionJobsController, ConversionOptions, CorpusCategory, SourceFormat } from "@/shared/conversion"

export type ConversionDraft = Omit<ConversionOptions, "source_format" | "category"> & { source_format: SourceFormat | ""; category: CorpusCategory | "" }
const initialDraft: ConversionDraft = { name: "", description: "", source_format: "", output_format: "corpus", category: "" }
const accept = [...new Set(SOURCE_FORMATS.flatMap(format => format.accept.split(",")))].join(",")
const categories: { value: CorpusCategory; label: string }[] = [{ value: "document", label: "Document" }, { value: "book", label: "Book" }, { value: "religious", label: "Religious text" }]

export function isDatasetSource(format: string): boolean {
    return format === "tf_zip" || format === "tei_zip"
}

export function validateConversionDraft(file: File | null, draft: ConversionDraft): string | null {
    if (!file) return "Choose a source file before continuing."
    const fileError = validateUploadFile(file, { accept, maxSize: MAX_UPLOAD_BYTES })
    if (fileError) return fileError
    const source = SOURCE_FORMATS.find(format => format.value === draft.source_format)
    if (!source) return "Choose the source format. ZIP archives need an explicit dataset type."
    if (validateUploadFile(file, { accept: source.accept })) return "The selected source format does not match this file."
    if (!draft.name.trim()) return "Enter a corpus name."
    if (isDatasetSource(draft.source_format) && draft.output_format !== "corpus") return "Source dataset ZIPs can only produce a .corpus archive."
    return null
}

function sourceError(file: File | null, format: ConversionDraft["source_format"]): string | null {
    if (!file) return "Choose a source file before continuing."
    const source = SOURCE_FORMATS.find(source => source.value === format)
    if (!source) return "Choose the source format. ZIP archives need an explicit dataset type."
    return validateUploadFile(file, { accept: source.accept, maxSize: MAX_UPLOAD_BYTES })
}

export function ConversionForm({ conversions, backendReady, onSubmitted, onClose }: { conversions: ConversionJobsController; backendReady: boolean; onSubmitted: (job: ConversionJob) => void; onClose: () => void }) {
    const [draft, setDraft] = useState<ConversionDraft>(initialDraft)
    const [step, setStep] = useState<ConversionReviewStep>(0)
    const [error, setError] = useState<string | null>(null)
    const [pending, setPending] = useState(false)
    const submitLock = useRef(false)
    const headingRef = useRef<HTMLHeadingElement>(null)
    const busy = pending || conversions.isSubmitting
    const onFilesChange = useCallback((files: FileWithPreview[]) => {
        const file = files[0]?.file
        setDraft(previous => ({
            ...previous,
            name: file ? file.name.replace(/\.(?:tei|tf)\.zip$/i, "").replace(/\.[^.]+$/, "") : "",
            source_format: file && !file.name.toLowerCase().endsWith(".zip") ? inferSourceFormat(file.name) ?? "" : "",
            output_format: "corpus",
        }))
        setStep(0)
        setError(null)
    }, [])
    const [upload, actions] = useFileUpload({ accept, maxSize: MAX_UPLOAD_BYTES, multiple: false, onFilesChange })
    const chosen = upload.files[0]?.file
    const file = chosen && chosen instanceof File ? chosen : null
    const dataset = isDatasetSource(draft.source_format)
    const validSource = sourceError(file, draft.source_format) === null && upload.errors.length === 0
    const validDraft = validateConversionDraft(file, draft) === null && upload.errors.length === 0
    const reachable: ConversionReviewStep = validDraft ? 2 : validSource ? 1 : 0
    const titles = ["Choose your source", "Shape the output", "Review conversion"] as const

    function goTo(next: ConversionReviewStep) {
        if (busy || next > reachable) return
        conversions.clearError()
        setError(null)
        setStep(next)
        requestAnimationFrame(() => headingRef.current?.focus())
    }

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (busy || submitLock.current) return
        const validation = step === 0 ? sourceError(file, draft.source_format) : validateConversionDraft(file, draft)
        if (validation || upload.errors.length) {
            setError(validation ?? upload.errors[0])
            return
        }
        if (step < 2) {
            goTo(step === 0 ? 1 : 2)
            return
        }
        if (!file || !draft.source_format || !backendReady) {
            setError("The sidecar must be ready before you submit a conversion.")
            return
        }
        submitLock.current = true
        setPending(true)
        setError(null)
        conversions.clearError()
        const options: ConversionOptions = {
            name: draft.name.trim(), description: draft.description.trim(), source_format: draft.source_format,
            output_format: draft.output_format, ...(draft.category ? { category: draft.category } : {}),
        }
        try {
            const job = await conversions.submit(file, options)
            if (job) onSubmitted(job)
            else setError("Submission did not complete. Check the request error above before trying again.")
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : "Could not submit the conversion. Your source and options have been kept.")
        } finally {
            submitLock.current = false
            setPending(false)
        }
    }

    return (
        <section aria-labelledby="conversion-form-heading" className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-xs">
            <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
                <div className="flex flex-col gap-1"><h2 id="conversion-form-heading" className="text-base font-semibold">New conversion</h2><p className="text-xs text-muted-foreground">From source document to a reusable corpus.</p></div>
                <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onClose}>Close</Button>
            </header>
            <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5 p-5" aria-busy={busy}>
                <ConversionReviewSteps current={step} reachable={reachable} onChange={goTo} disabled={busy} />
                <div className="flex flex-col gap-1"><h3 ref={headingRef} tabIndex={-1} className="text-lg font-semibold tracking-tight outline-none">{titles[step]}</h3><p className="text-sm text-muted-foreground">{step === 0 ? "Choose one supported file. It stays local until you confirm submission." : step === 1 ? "Name the corpus and choose its packaging." : "Confirm the source and options before the conversion starts."}</p></div>
                {step === 0 && (
                    <FieldGroup>
                        <ConversionSourceAttachment upload={upload} actions={actions} disabled={busy} />
                        <SupportedConversionSources />
                        <Field required disabled={busy} invalid={Boolean(error && !draft.source_format)}>
                            <FieldLabel>Source format <FieldRequiredIndicator /></FieldLabel>
                            <NativeSelect value={draft.source_format} onChange={event => {
                                const source = SOURCE_FORMATS.find(format => format.value === event.target.value)
                                setDraft(previous => ({ ...previous, source_format: source?.value ?? "", output_format: isDatasetSource(source?.value ?? "") ? "corpus" : previous.output_format }))
                                setError(null)
                            }}>
                                <NativeSelectOption value="">Choose a source format</NativeSelectOption>
                                {SOURCE_FORMATS.map(format => <NativeSelectOption key={format.value} value={format.value} disabled={Boolean(file && validateUploadFile(file, { accept: format.accept }))}>{format.label}</NativeSelectOption>)}
                            </NativeSelect>
                            <FieldHelper className="text-xs">{file?.name.toLowerCase().endsWith(".zip") ? "ZIP contents cannot be inferred from the filename. Choose Text-Fabric or TEI ZIP explicitly." : "Detected from the extension when possible. For XML, choose XML or TEI to match the document."}</FieldHelper>
                            <FieldError>Choose the source format.</FieldError>
                        </Field>
                    </FieldGroup>
                )}
                {step === 1 && (
                    <FieldGroup>
                        <Field required disabled={busy} invalid={Boolean(error && !draft.name.trim())}>
                            <FieldLabel>Corpus name <FieldRequiredIndicator /></FieldLabel>
                            <Input name="name" value={draft.name} onChange={event => { setDraft(previous => ({ ...previous, name: event.target.value })); setError(null) }} placeholder="Name this corpus" autoComplete="off" />
                            <FieldError>Enter a corpus name.</FieldError>
                        </Field>
                        <Field disabled={busy}>
                            <FieldLabel>Description <span className="font-normal text-muted-foreground">(optional)</span></FieldLabel>
                            <Textarea name="description" value={draft.description} onChange={event => setDraft(previous => ({ ...previous, description: event.target.value }))} placeholder="A brief description of this source" rows={3} />
                        </Field>
                        <FieldSet disabled={busy} className="gap-2">
                            <FieldLegend variant="label" className="mb-0">Output format</FieldLegend>
                            <RadioGroup name="output_format" value={draft.output_format} onValueChange={({ value }) => {
                                const output = OUTPUT_FORMATS.find(format => format.value === value)
                                if (output) setDraft(previous => ({ ...previous, output_format: output.value }))
                            }} className="grid gap-2 sm:grid-cols-3" aria-label="Output format">
                                {OUTPUT_FORMATS.map(format => (
                                    <RadioGroupItem key={format.value} value={format.value} disabled={dataset && format.value !== "corpus"} className="min-h-20 items-start rounded-lg border border-input p-3 data-[state=checked]:border-primary/40 data-[state=checked]:bg-accent">
                                        <span className="flex flex-col gap-1"><span>{format.label}</span><span className="text-xs font-normal leading-relaxed text-muted-foreground">{format.description}</span></span>
                                    </RadioGroupItem>
                                ))}
                            </RadioGroup>
                            {dataset && <p className="text-xs text-muted-foreground">Source dataset ZIPs only support .corpus output.</p>}
                        </FieldSet>
                        <Field disabled={busy}>
                            <FieldLabel>Category <span className="font-normal text-muted-foreground">(optional)</span></FieldLabel>
                            <NativeSelect name="category" value={draft.category} onChange={event => {
                                const category = categories.find(category => category.value === event.target.value)
                                setDraft(previous => ({ ...previous, category: category?.value ?? "" }))
                            }}><NativeSelectOption value="">Let the backend choose</NativeSelectOption>{categories.map(category => <NativeSelectOption key={category.value} value={category.value}>{category.label}</NativeSelectOption>)}</NativeSelect>
                        </Field>
                    </FieldGroup>
                )}
                {step === 2 && file && (
                    <div className="flex flex-col gap-4">
                        <dl className="grid grid-cols-[minmax(5rem,auto)_1fr] gap-x-5 gap-y-3 rounded-xl border border-border bg-muted/30 p-4 text-sm">
                            <dt className="text-muted-foreground">Source</dt><dd className="min-w-0 break-all font-medium">{file.name}<span className="mt-1 block text-xs font-normal text-muted-foreground">{formatBytes(file.size)} · {SOURCE_FORMATS.find(source => source.value === draft.source_format)?.label}</span></dd>
                            <dt className="text-muted-foreground">Name</dt><dd className="min-w-0 break-words font-medium">{draft.name.trim()}</dd>
                            <dt className="text-muted-foreground">Description</dt><dd className="min-w-0 whitespace-pre-wrap break-words">{draft.description.trim() || "Not provided"}</dd>
                            <dt className="text-muted-foreground">Output</dt><dd className="font-medium">{OUTPUT_FORMATS.find(format => format.value === draft.output_format)?.label}</dd>
                            <dt className="text-muted-foreground">Category</dt><dd>{categories.find(category => category.value === draft.category)?.label ?? "Backend default"}</dd>
                        </dl>
                        <Alert><ShieldCheck aria-hidden="true" strokeWidth={1.5} /><AlertTitle>Ready to submit</AlertTitle><AlertDescription className="text-xs leading-relaxed">The source bytes will be sent to your configured sidecar. Switching tabs does not cancel a submitted job. Conversion may take several minutes; only backend-reported stages are shown.</AlertDescription></Alert>
                    </div>
                )}
                {error && <Alert variant="destructive" role="alert"><AlertTitle>Check this conversion</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
                <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
                    <Button type="button" variant="ghost" disabled={busy || step === 0} onClick={() => goTo(step === 2 ? 1 : 0)}><ArrowLeft aria-hidden="true" />Back</Button>
                    <Button type="submit" disabled={busy || (step === 2 && !backendReady)} aria-busy={busy}>
                        {busy ? <><LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />Submitting…</> : step === 2 ? <><FileCheck2 aria-hidden="true" />Start conversion</> : <>Continue<ArrowRight aria-hidden="true" /></>}
                    </Button>
                </footer>
            </form>
        </section>
    )
}
