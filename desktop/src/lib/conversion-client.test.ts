import { afterEach, describe, expect, mock, test } from "bun:test"
import { ConversionClient, type ConversionRuntime, type ConversionSnapshot } from "./conversion-client"
import {
    buildConversionForm,
    ConversionRequestError,
    inferSourceFormat,
    isTerminalJob,
    MAX_UPLOAD_BYTES,
    parseConversionJob,
    parseConversionList,
    requireSuccessfulResponse,
    safeDownloadFilename
} from "./conversion"
import type { ConversionJob, ConversionOptions } from "../shared/conversion"

const ENDPOINT = "http://127.0.0.1:8001"
const POLL_DELAY = 1500
const READ_DEADLINE = 30_000
const UPLOAD_DEADLINE = 120_000
const options: ConversionOptions = {
    name: "  Example corpus  ",
    description: "  A document  ",
    source_format: "plain",
    output_format: "corpus"
}
const source = () => new File(["Example source text"], "source.txt", { type: "text/plain" })
const json = (value: unknown, status = 200) => Response.json(value, { status })
const list = (jobs: ConversionJob[], total = jobs.length) => json({ jobs, total })
// Drain promise chains, including Response body decoding, without advancing runtime timers.
const flush = () => new Promise<void>((resolve) => setImmediate(resolve))

function job(overrides: Partial<ConversionJob> = {}): ConversionJob {
    return {
        id: "job-1",
        name: "Example corpus",
        display_name: null,
        source_format: "plain",
        output_format: "corpus",
        status: "queued",
        created_at: 1000,
        started_at: null,
        finished_at: null,
        error: null,
        logs: [],
        last_log: null,
        events: [],
        steps: [],
        validation: null,
        result_filename: "Example corpus.corpus",
        download_ready: false,
        ...overrides
    }
}

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((done, fail) => {
        resolve = done
        reject = fail
    })
    return { promise, resolve, reject }
}

interface Scheduled {
    callback: () => void
    delay: number
    active: boolean
}

class TestRuntime implements ConversionRuntime {
    time = 1_700_000_000_000
    requests: { url: string; init: RequestInit; response: ReturnType<typeof deferred<Response>> }[] = []
    scheduled: Scheduled[] = []
    save = mock((_blob: Blob, _filename: string) => {})
    now = () => this.time
    // Deliberately allow responses after abort to exercise generation guards, not just transport cancellation.
    fetch: typeof fetch = Object.assign(
        (input: Parameters<typeof fetch>[0], init: RequestInit = {}) => {
            const response = deferred<Response>()
            this.requests.push({ url: String(input), init, response })
            return response.promise
        },
        { preconnect: () => {} }
    )
    schedule = (callback: () => void, delay: number) => {
        const timer = { callback, delay, active: true }
        this.scheduled.push(timer)
        return () => {
            timer.active = false
        }
    }
    timers(delay: number): Scheduled[] {
        return this.scheduled.filter((timer) => timer.active && timer.delay === delay)
    }
    async fire(delay: number): Promise<void> {
        const timers = this.timers(delay)
        expect(timers).toHaveLength(1)
        timers[0].active = false
        this.time += delay
        timers[0].callback()
        await flush()
    }
    async respond(index: number, response: Response): Promise<void> {
        const request = this.requests[index]
        if (!request) throw new Error(`No fetch request at index ${index}`)
        request.response.resolve(response)
        await flush()
    }
    async reject(index: number, error: Error): Promise<void> {
        const request = this.requests[index]
        if (!request) throw new Error(`No fetch request at index ${index}`)
        request.response.reject(error)
        await flush()
    }
}

const clients = new Set<ConversionClient>()
afterEach(() => {
    for (const client of clients) client.stop()
    clients.clear()
})
function clientFor(
    runtime: TestRuntime,
    endpoint: string | null = ENDPOINT,
    token = "request-token"
): ConversionClient {
    const client = new ConversionClient(endpoint, token, runtime)
    clients.add(client)
    return client
}
async function started(jobs: ConversionJob[] = [], token = "request-token", endpoint = ENDPOINT) {
    const runtime = new TestRuntime()
    const client = clientFor(runtime, endpoint, token)
    client.start()
    await flush()
    expect(runtime.requests).toHaveLength(1)
    await runtime.respond(0, list(jobs))
    return { client, runtime }
}

async function poll(runtime: TestRuntime, responses: Response[]): Promise<void> {
    const first = runtime.requests.length
    await runtime.fire(POLL_DELAY)
    expect(runtime.requests).toHaveLength(first + responses.length)
    await Promise.all(responses.map((response, index) => runtime.respond(first + index, response)))
}

describe("ConversionClient background tracking", () => {
    test.each(["succeeded", "failed"] as const)(
        "polls only active jobs without subscribers and stops at %s",
        async (status) => {
            const active = job()
            const terminal = job({ id: "old-job", status: "failed", created_at: 900 })
            const { client, runtime } = await started([terminal, active])
            expect(client.getSnapshot().jobs.map((item) => item.id)).toEqual([active.id, terminal.id])
            expect(runtime.scheduled.map((timer) => timer.delay)).toEqual([READ_DEADLINE, POLL_DELAY])
            expect(runtime.timers(READ_DEADLINE)).toHaveLength(0)

            await poll(runtime, [json({ ...active, status: "running", logs: ["Parsing"] })])
            expect(runtime.requests[1].url).toBe(`${ENDPOINT}/convert/job-1`)
            expect(client.getSnapshot().jobs[0].status).toBe("running")
            expect(runtime.timers(POLL_DELAY)).toHaveLength(1)
            await poll(runtime, [json({ ...active, status, download_ready: status === "succeeded" })])
            expect(runtime.requests.slice(1).every((request) => request.url.endsWith("/convert/job-1"))).toBe(true)
            expect(client.getSnapshot().jobs[0].status).toBe(status)
            expect(runtime.scheduled.filter((timer) => timer.active)).toHaveLength(0)
            await flush()
            expect(runtime.requests).toHaveLength(3)
        }
    )

    test("does not flicker loading or replace an unchanged snapshot during background updates", async () => {
        const { client, runtime } = await started([job()])
        const updates: ConversionSnapshot[] = []
        const unsubscribe = client.subscribe(() => updates.push(client.getSnapshot()))
        const before = client.getSnapshot()
        await runtime.fire(POLL_DELAY)
        expect(client.getSnapshot()).toBe(before)
        expect(updates).toHaveLength(0)
        expect(runtime.timers(READ_DEADLINE)).toHaveLength(1)
        await runtime.respond(1, json(job({ status: "running", last_log: "Parsing" })))
        expect(updates).toHaveLength(1)
        expect(updates.every((snapshot) => !snapshot.isLoading)).toBe(true)

        const running = client.getSnapshot()
        await poll(runtime, [json(job({ status: "running", last_log: "Parsing" }))])
        expect(client.getSnapshot()).toBe(running)
        expect(updates).toHaveLength(1)
        unsubscribe()
        await poll(runtime, [json(job({ status: "succeeded" }))])
        expect(updates).toHaveLength(1)
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)
    })

    test("reads every list page so an old active job remains tracked", async () => {
        const runtime = new TestRuntime()
        const client = clientFor(runtime)
        const recent = Array.from({ length: 200 }, (_, index) =>
            job({ id: `done-${index}`, status: "succeeded", created_at: 2000 + index })
        )
        client.start()
        const refresh = client.refresh()
        expect(client.refresh()).toBe(refresh)
        expect(client.getSnapshot().isLoading).toBe(true)
        await flush()
        await runtime.respond(0, list(recent, 201))
        expect(runtime.requests[1].url).toBe(`${ENDPOINT}/convert?offset=200&limit=200`)
        expect(client.getSnapshot().isLoading).toBe(true)
        await runtime.respond(1, list([job()], 201))
        await refresh
        expect(client.getSnapshot().jobs).toHaveLength(201)
        expect(client.getSnapshot().isLoading).toBe(false)
        await poll(runtime, [json(job({ status: "succeeded" }))])
        expect(runtime.requests[2].url).toBe(`${ENDPOINT}/convert/job-1`)
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)
    })

    test("retries a failed initial list as a list request rather than an empty active-job poll", async () => {
        const runtime = new TestRuntime()
        const client = clientFor(runtime)
        client.start()
        await flush()
        await runtime.respond(0, json({ detail: "Backend restarting" }, 503))
        expect(client.getSnapshot()).toMatchObject({ jobs: [], isLoading: false })
        expect(client.getSnapshot().error).toContain("Backend restarting")
        await poll(runtime, [list([job()])])
        expect(runtime.requests[1].url).toBe(`${ENDPOINT}/convert?offset=0&limit=200`)
        expect(client.getSnapshot().error).toBeNull()
        await poll(runtime, [json(job({ status: "succeeded" }))])
        expect(runtime.requests[2].url).toBe(`${ENDPOINT}/convert/job-1`)
    })

    test("drops a confirmed expired job and stops tracking it", async () => {
        const { client, runtime } = await started([job()])
        await poll(runtime, [json({ detail: "Not found" }, 404)])
        expect(client.getSnapshot().jobs).toEqual([])
        expect(client.getSnapshot().error).toContain("no longer available")
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)
    })

    test("rejects a status response for a different id without replacing the accepted job", async () => {
        const { client, runtime } = await started([job()])
        await poll(runtime, [json(job({ id: "someone-else", status: "succeeded" }))])
        expect(client.getSnapshot().jobs).toEqual([job()])
        expect(client.getSnapshot().error).toContain("different job id")
        expect(runtime.timers(POLL_DELAY)).toHaveLength(1)
    })
})

describe("ConversionClient submission and deadlines", () => {
    test("accepted POST survives a failed GET and a racing list without re-POSTing", async () => {
        const { client, runtime } = await started()
        const acceptedAt = runtime.time / 1000
        const submission = client.submit(source(), options)
        await flush()
        await runtime.respond(1, json({ job_id: "accepted/id" }, 202))
        const accepted = await submission
        if (!accepted) throw new Error("The accepted upload must return its job")
        expect(accepted).toMatchObject({
            id: "accepted/id",
            status: "queued",
            name: "Example corpus",
            created_at: acceptedAt
        })
        expect(client.getSnapshot().isSubmitting).toBe(false)
        await poll(runtime, [json({ detail: "Temporary status outage" }, 503)])
        expect(client.getSnapshot().jobs).toEqual([accepted])
        expect(client.getSnapshot().error).toContain("Temporary status outage")
        expect(runtime.requests[2].url).toBe(`${ENDPOINT}/convert/accepted%2Fid`)

        const refresh = client.refresh()
        await flush()
        await runtime.respond(3, list([]))
        await refresh
        expect(client.getSnapshot().jobs).toEqual([accepted])
        await poll(runtime, [json(job({ id: "accepted/id", status: "succeeded", download_ready: true }))])
        expect(client.getSnapshot().jobs[0].id).toBe("accepted/id")
        expect(client.getSnapshot().jobs[0].status).toBe("succeeded")
        expect(client.getSnapshot().error).toBeNull()
        expect(runtime.requests.filter((request) => request.init.method === "POST")).toHaveLength(1)
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)
    })

    test("submit is singleflight, sends authenticated multipart data, and releases after acceptance", async () => {
        const { client, runtime } = await started()
        const first = client.submit(source(), { ...options, category: "book" })
        expect(client.submit(source(), { ...options, name: "Duplicate" })).toBe(first)
        expect(client.getSnapshot().isSubmitting).toBe(true)
        await flush()
        expect(runtime.requests).toHaveLength(2)
        const request = runtime.requests[1]
        expect(request.url).toBe(`${ENDPOINT}/convert`)
        const headers = new Headers(request.init.headers)
        expect(headers.get("Authorization")).toBe("Bearer request-token")
        expect(headers.has("Content-Type")).toBe(false)
        expect(request.init.body).toBeInstanceOf(FormData)
        const body = request.init.body as FormData
        expect(body.get("name")).toBe("Example corpus")
        expect(body.get("description")).toBe("A document")
        expect(body.get("category")).toBe("book")
        expect(runtime.timers(UPLOAD_DEADLINE)).toHaveLength(1)
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)
        await runtime.respond(1, json({ job_id: "first" }, 202))
        expect((await first)?.id).toBe("first")
        expect(runtime.timers(UPLOAD_DEADLINE)).toHaveLength(0)
        expect(client.getSnapshot().isSubmitting).toBe(false)

        const second = client.submit(source(), options)
        expect(second).not.toBe(first)
        await flush()
        await runtime.respond(2, json({ job_id: "second" }, 202))
        expect((await second)?.id).toBe("second")
        expect(
            client
                .getSnapshot()
                .jobs.map((item) => item.id)
                .sort()
        ).toEqual(["first", "second"])
        expect(runtime.timers(POLL_DELAY)).toHaveLength(1)
    })

    test("upload timeout warns acceptance is uncertain and never automatically resubmits", async () => {
        const { client, runtime } = await started()
        const submission = client.submit(source(), options)
        await flush()
        const request = runtime.requests[1]
        request.init.signal?.addEventListener(
            "abort",
            () => request.response.reject(new DOMException("Aborted", "AbortError")),
            { once: true }
        )
        await runtime.fire(UPLOAD_DEADLINE)
        expect(await submission).toBeNull()
        expect(request.init.signal?.aborted).toBe(true)
        expect(client.getSnapshot().error).toContain("server may have accepted it")
        expect(client.getSnapshot().error).toContain("refresh the job list")
        expect(client.getSnapshot().isSubmitting).toBe(false)
        expect(runtime.scheduled.filter((timer) => timer.active)).toHaveLength(0)
        expect(runtime.requests.filter((item) => item.init.method === "POST")).toHaveLength(1)
    })

    test("read timeout aborts the request but retains the job and schedules status retry", async () => {
        const { client, runtime } = await started([job()])
        await runtime.fire(POLL_DELAY)
        const request = runtime.requests[1]
        request.init.signal?.addEventListener(
            "abort",
            () => request.response.reject(new DOMException("Aborted", "AbortError")),
            { once: true }
        )
        await runtime.fire(READ_DEADLINE)
        expect(request.init.signal?.aborted).toBe(true)
        expect(client.getSnapshot().jobs).toEqual([job()])
        expect(client.getSnapshot().error).toContain("timed out")
        expect(runtime.timers(POLL_DELAY)).toHaveLength(1)
        await poll(runtime, [json(job({ status: "succeeded" }))])
        expect(client.getSnapshot().error).toBeNull()
    })
})

describe("ConversionClient disposal and stale responses", () => {
    test.each([false, true])(
        "stop aborts an in-flight list and ignores late completion (rejected: %j)",
        async (rejected) => {
            const runtime = new TestRuntime()
            const client = clientFor(runtime)
            client.start()
            const pending = client.refresh()
            await flush()
            client.stop()
            const stopped = client.getSnapshot()
            const listener = mock(() => {})
            client.subscribe(listener)
            expect(runtime.requests[0].init.signal?.aborted).toBe(true)
            if (rejected) await runtime.reject(0, new Error("Late network failure"))
            else await runtime.respond(0, list([job()]))
            await pending
            await client.refresh()
            expect(client.getSnapshot()).toBe(stopped)
            expect(listener).not.toHaveBeenCalled()
            expect(runtime.scheduled.filter((timer) => timer.active)).toHaveLength(0)
            expect(runtime.requests).toHaveLength(1)
        }
    )

    test("stop cancels the poll timer and leaves no automatic request", async () => {
        const { client, runtime } = await started([job()])
        expect(runtime.timers(POLL_DELAY)).toHaveLength(1)
        client.stop()
        await flush()
        expect(runtime.scheduled.filter((timer) => timer.active)).toHaveLength(0)
        expect(runtime.requests).toHaveLength(1)
    })

    const replacements = [
        { change: "token", endpoint: ENDPOINT, token: "new-identity" },
        { change: "endpoint", endpoint: "http://127.0.0.1:9000", token: "request-token" }
    ]
    const operations = ["list", "submit", "download"] as const
    test.each(replacements.flatMap((replacement) => operations.map((operation) => ({ ...replacement, operation }))))(
        "$change replacement aborts the disposed client's $operation and ignores its late result",
        async ({ endpoint, token, operation }) => {
            const runtime = new TestRuntime()
            const old = clientFor(runtime)
            old.start()
            await flush()
            let pending: Promise<unknown>
            let oldIndex = 0
            const downloadable = job({ status: "succeeded", download_ready: true })
            if (operation === "list") pending = old.refresh()
            else {
                await runtime.respond(0, list([]))
                pending = operation === "submit" ? old.submit(source(), options) : old.download(downloadable)
                await flush()
                oldIndex = 1
            }
            old.stop()
            const stopped = old.getSnapshot()
            const listener = mock(() => {})
            old.subscribe(listener)
            expect(runtime.requests[oldIndex].init.signal?.aborted).toBe(true)

            const replacement = clientFor(runtime, endpoint, token)
            replacement.start()
            await flush()
            const newIndex = runtime.requests.length - 1
            expect(runtime.requests[newIndex].url).toBe(`${endpoint}/convert?offset=0&limit=200`)
            expect(new Headers(runtime.requests[newIndex].init.headers).get("Authorization")).toBe(`Bearer ${token}`)
            const replacementJob = job({ id: "replacement-job", status: "succeeded" })
            await runtime.respond(newIndex, list([replacementJob]))
            await runtime.respond(
                oldIndex,
                operation === "submit"
                    ? json({ job_id: "obsolete-acceptance" }, 202)
                    : operation === "download"
                      ? new Response("obsolete bytes")
                      : list([job()])
            )
            await pending
            expect(old.getSnapshot()).toBe(stopped)
            expect(listener).not.toHaveBeenCalled()
            expect(replacement.getSnapshot().jobs).toEqual([replacementJob])
            expect(runtime.save).not.toHaveBeenCalled()
            expect(runtime.scheduled.filter((timer) => timer.active)).toHaveLength(0)
        }
    )

    test("a stopped generation cannot disable list retry for a restarted client", async () => {
        const runtime = new TestRuntime()
        const client = clientFor(runtime)
        client.start()
        const stale = client.refresh()
        await flush()
        client.stop()
        client.start()
        await flush()
        await runtime.respond(1, json({ detail: "New connection is restarting" }, 503))
        const current = client.getSnapshot()
        await runtime.respond(0, list([job({ id: "stale-job" })]))
        await stale
        expect(client.getSnapshot()).toBe(current)
        await runtime.fire(POLL_DELAY)
        expect(runtime.requests).toHaveLength(3)
        expect(runtime.requests[2].url).toBe(`${ENDPOINT}/convert?offset=0&limit=200`)
        await runtime.respond(2, list([]))
        expect(client.getSnapshot().error).toBeNull()
    })

    test("stop before submit dispatch prevents an obsolete POST even after immediate restart", async () => {
        const { client, runtime } = await started()
        const obsolete = client.submit(source(), options)
        client.stop()
        client.start()
        await flush()
        const dispatched = runtime.requests.slice(1)
        await Promise.all(
            dispatched.map((request, index) =>
                runtime.respond(
                    index + 1,
                    request.init.method === "POST" ? json({ job_id: "obsolete" }, 202) : list([])
                )
            )
        )
        expect(await obsolete).toBeNull()
        expect(dispatched.filter((request) => request.init.method === "POST")).toHaveLength(0)
        expect(client.getSnapshot().jobs).toEqual([])
    })
})

describe("ConversionClient authentication and downloads", () => {
    test.each(["list", "poll"] as const)("401 on %s stops automatic retry until manual refresh", async (operation) => {
        const runtime = new TestRuntime()
        const client = clientFor(runtime)
        client.start()
        await flush()
        if (operation === "poll") {
            await runtime.respond(0, list([job()]))
            await runtime.fire(POLL_DELAY)
        }
        await runtime.respond(runtime.requests.length - 1, json({ detail: "Expired token" }, 401))
        expect(client.getSnapshot().error).toContain("Authentication failed")
        expect(runtime.scheduled.filter((timer) => timer.active)).toHaveLength(0)
        const count = runtime.requests.length
        client.clearError()
        client.start()
        await flush()
        expect(runtime.requests).toHaveLength(count)
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)

        const refresh = client.refresh()
        await flush()
        await runtime.respond(count, list([job()]))
        await refresh
        expect(client.getSnapshot().error).toBeNull()
        expect(runtime.timers(POLL_DELAY)).toHaveLength(1)
        await poll(runtime, [json(job({ status: "succeeded" }))])
    })

    test("a new identity resumes tracking after the old identity is blocked", async () => {
        const runtime = new TestRuntime()
        const old = clientFor(runtime, ENDPOINT, "expired-token")
        old.start()
        await flush()
        await runtime.respond(0, json({ detail: "Expired" }, 401))
        old.stop()
        const replacement = clientFor(runtime, ENDPOINT, "fresh-token")
        replacement.start()
        await flush()
        expect(new Headers(runtime.requests[1].init.headers).get("Authorization")).toBe("Bearer fresh-token")
        await runtime.respond(1, list([job()]))
        await poll(runtime, [json(job({ status: "succeeded" }))])
        expect(replacement.getSnapshot().jobs[0].status).toBe("succeeded")
        expect(old.getSnapshot().jobs).toEqual([])
    })

    test("any 401 in a multi-job poll blocks retry even when another job returns 503", async () => {
        const first = job({ id: "auth-failure", created_at: 2000 })
        const second = job({ id: "service-failure" })
        const { client, runtime } = await started([first, second])
        await poll(runtime, [json({ detail: "Expired token" }, 401), json({ detail: "Service unavailable" }, 503)])
        expect(client.getSnapshot().jobs).toEqual([first, second])
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)
    })

    test("a download 401 also cancels an already scheduled active-job poll", async () => {
        const done = job({ id: "downloadable", status: "succeeded", download_ready: true })
        const { client, runtime } = await started([job(), done])
        const downloading = client.download(done).then(
            () => null,
            (error: unknown) => error
        )
        await flush()
        await runtime.respond(1, json({ detail: "Expired token" }, 401))
        expect(await downloading).toBeInstanceOf(ConversionRequestError)
        expect(client.getSnapshot().error).toContain("Authentication failed")
        expect(runtime.timers(POLL_DELAY)).toHaveLength(0)
    })

    test("downloads with the auth header, encoded job id, and a safe server-provided name", async () => {
        const done = job({ id: "result/id ?", status: "succeeded", download_ready: true })
        const { client, runtime } = await started([done], "download-token", `${ENDPOINT}/`)
        const downloading = client.download(done)
        await flush()
        const request = runtime.requests[1]
        expect(request.url).toBe(`${ENDPOINT}/convert/result%2Fid%20%3F/download`)
        expect(new Headers(request.init.headers).get("Authorization")).toBe("Bearer download-token")
        expect(request.url).not.toContain("download-token")
        expect(runtime.timers(READ_DEADLINE)).toHaveLength(1)
        const bytes = new Uint8Array([0, 1, 2, 255])
        await runtime.respond(
            1,
            new Response(bytes, {
                headers: {
                    "Content-Disposition":
                        "attachment; filename=ignored.corpus; filename*=UTF-8''..%2Ffolder%5Cunsafe%00.corpus"
                }
            })
        )
        await downloading
        expect(runtime.save).toHaveBeenCalledTimes(1)
        const [blob, filename] = runtime.save.mock.calls[0]
        expect(filename).toBe("_folder_unsafe_.corpus")
        expect(new Uint8Array(await blob.arrayBuffer())).toEqual(bytes)
        expect(runtime.timers(READ_DEADLINE)).toHaveLength(0)
    })

    test("anonymous downloads omit Authorization and sanitize the fallback filename", async () => {
        const done = job({ status: "succeeded", download_ready: true, result_filename: "../../unsafe\\name.corpus" })
        const { client, runtime } = await started([done], "")
        const downloading = client.download(done)
        await flush()
        expect(new Headers(runtime.requests[1].init.headers).has("Authorization")).toBe(false)
        await runtime.respond(1, new Response("corpus bytes"))
        await downloading
        expect(runtime.save.mock.calls[0][1]).toBe("_.._unsafe_name.corpus")
    })

    test.each([
        job(),
        job({ status: "failed", download_ready: true }),
        job({ status: "succeeded", download_ready: false })
    ])("does not fetch or save a result that is not ready (%j)", async (notReady) => {
        const { client, runtime } = await started()
        await expect(client.download(notReady)).rejects.toThrow("not ready to download")
        expect(runtime.requests).toHaveLength(1)
        expect(runtime.save).not.toHaveBeenCalled()
    })
})

describe("conversion utilities", () => {
    test.each([
        ["BOOK.EPUB", "epub"],
        ["page.htm", "html"],
        ["book.tei", "tei"],
        ["book.xml", "xml"],
        ["document.PDF", "pdf"],
        ["notes.md", "plain"],
        ["dataset.tf.zip", null],
        ["dataset.tei.zip", null],
        ["unknown.docx", null]
    ] as const)("infers %s as %s without guessing ZIP contents", (filename, expected) => {
        expect(inferSourceFormat(filename)).toBe(expected)
    })

    test("multipart form trims metadata and omits an unspecified category", () => {
        const body = buildConversionForm(source(), options)
        expect(body.get("name")).toBe("Example corpus")
        expect(body.get("description")).toBe("A document")
        expect(body.get("source_format")).toBe("plain")
        expect(body.get("output_format")).toBe("corpus")
        expect(body.has("category")).toBe(false)
        const file = body.get("file")
        expect(file).toBeInstanceOf(File)
        expect((file as File).name).toBe("source.txt")
    })

    test("rejects empty/oversized source files and empty names before upload", () => {
        expect(() => buildConversionForm(new File([], "empty.txt"), options)).toThrow("nonempty source file")
        const oversized = source()
        Object.defineProperty(oversized, "size", { value: MAX_UPLOAD_BYTES + 1 })
        expect(() => buildConversionForm(oversized, options)).toThrow("500 MiB")
        expect(() => buildConversionForm(source(), { ...options, name: " \n " })).toThrow("corpus name")
    })

    test.each(["tf_zip", "tei_zip"] as const)("%s permits only corpus output", (source_format) => {
        for (const output_format of ["cusx", "ctei"] as const) {
            expect(() => buildConversionForm(source(), { ...options, source_format, output_format })).toThrow(
                "only produce a .corpus"
            )
        }
        expect(buildConversionForm(source(), { ...options, source_format }).get("output_format")).toBe("corpus")
    })

    test("parses telemetry defensively and keeps conversion jobs separate from ingest", () => {
        const event = { sequence: 1, timestamp: 1000, level: "info", message: "Parsing", stage: "parse" }
        const step = { id: "parse", title: "Parse source", status: "running" }
        const parsed = parseConversionJob({
            ...job(),
            logs: ["Parsing", 42],
            started_at: Infinity,
            finished_at: "not a date",
            display_name: 42,
            events: [
                event,
                { ...event, sequence: 0 },
                { ...event, timestamp: NaN },
                { ...event, level: "fatal" },
                null
            ],
            steps: [step, { ...step, status: "unknown" }, null],
            validation: ["not a record"]
        })
        expect(parsed).toMatchObject({
            logs: ["Parsing"],
            events: [event],
            steps: [step],
            started_at: null,
            finished_at: null,
            display_name: null,
            validation: null
        })
        expect(parseConversionList({ jobs: [job(), { ...job(), id: "ingest", source_format: "docling" }] })).toEqual([
            job()
        ])
        expect(() => parseConversionList({ jobs: [job({ status: "running", id: "" })] })).toThrow(
            "invalid conversion job"
        )
        expect(() => parseConversionList({ jobs: null })).toThrow("invalid job list")
    })

    test.each([
        { value: null },
        { value: [] },
        { value: { ...job(), id: "" } },
        { value: { ...job(), created_at: Infinity } },
        { value: { ...job(), status: "unknown" } }
    ])("rejects malformed job payload $value", ({ value }) => {
        expect(() => parseConversionJob(value)).toThrow("invalid conversion job")
    })

    test.each(["queued", "running", "succeeded", "failed"] as const)("terminal predicate recognizes %s", (status) => {
        expect(isTerminalJob(job({ status }))).toBe(status === "succeeded" || status === "failed")
    })

    test("HTTP errors retain status and nested validation detail without duplicate messages", async () => {
        const response = json(
            { detail: [{ msg: "Invalid source" }, { reasons: ["Invalid source", "Missing title"] }] },
            422
        )
        try {
            await requireSuccessfulResponse(response)
            throw new Error("Expected response validation to reject")
        } catch (error) {
            expect(error).toBeInstanceOf(ConversionRequestError)
            expect(error).toMatchObject({
                status: 422,
                message: "Conversion request failed (HTTP 422).\nInvalid source\nMissing title"
            })
        }
        const success = new Response("bytes")
        expect(await requireSuccessfulResponse(success)).toBe(success)
        await expect(requireSuccessfulResponse(new Response("not JSON", { status: 502 }))).rejects.toThrow("HTTP 502")
    })

    test.each([
        [401, "Authentication failed"],
        [413, "500 MiB"],
        [429, "queue is full"]
    ] as const)("HTTP %i has an actionable error", async (status, message) => {
        await expect(requireSuccessfulResponse(json({ detail: "Backend detail" }, status))).rejects.toThrow(message)
    })

    test.each([
        { disposition: 'attachment; filename="report.corpus"', fallback: "fallback.corpus", expected: "report.corpus" },
        { disposition: "attachment; filename=report.corpus", fallback: "fallback.corpus", expected: "report.corpus" },
        {
            disposition: "attachment; filename=plain.corpus; filename*=UTF-8''Caf%C3%A9.corpus",
            fallback: "fallback.corpus",
            expected: "Café.corpus"
        },
        {
            disposition: "attachment; filename=plain.corpus; filename*=UTF-8''%ZZ",
            fallback: "fallback.corpus",
            expected: "plain.corpus"
        },
        {
            disposition: 'attachment; filename="../unsafe\\name\u0000\u007f.corpus"',
            fallback: "fallback.corpus",
            expected: "_unsafe_name__.corpus"
        },
        { disposition: null, fallback: "..\\unsafe/name.corpus", expected: "_unsafe_name.corpus" },
        { disposition: null, fallback: "...", expected: "conversion.corpus" },
        { disposition: null, fallback: "   ", expected: "conversion.corpus" }
    ])("safe filename: $expected", ({ disposition, fallback, expected }) => {
        expect(safeDownloadFilename(disposition, fallback)).toBe(expected)
    })
})
