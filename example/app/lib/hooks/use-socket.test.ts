import { describe, expect, test } from "bun:test"
import {
  JobGoneError,
  pollJobStatus,
  type JobStatusMessage,
  type PollFailureReason,
} from "./use-socket"

/**
 * The bounded-poll contract (issue #189): `pollJobStatus` must always end --
 * on a terminal job status, a 404 for a tracked job (`JobGoneError`), an
 * overall deadline, or a sustained run of fetch failures -- and report the
 * give-up reason exactly once via `onFailure`. It must never spin forever.
 *
 * Tests use real timers with millisecond intervals, matching the repo's
 * bun:test conventions (no fake-timer harness).
 */

const message = (status: JobStatusMessage["status"]): JobStatusMessage => ({
  id: "job-1",
  source_format: "epub",
  name: "book",
  display_name: null,
  status,
  created_at: 0,
  started_at: null,
  finished_at: null,
  error: null,
  logs: [],
  last_log: null,
  result_filename: "book.corpus",
  download_ready: status === "succeeded",
})

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** Poll with tiny timings and record everything the poll reports. */
const runPoll = (
  fetchStatus: () => Promise<JobStatusMessage>,
  overrides: { deadlineMs?: number; maxConsecutiveErrors?: number } = {}
) => {
  const messages: JobStatusMessage[] = []
  const failures: PollFailureReason[] = []
  const stop = pollJobStatus(fetchStatus, (m) => messages.push(m), {
    intervalMs: 1,
    deadlineMs: overrides.deadlineMs ?? 5_000,
    maxConsecutiveErrors: overrides.maxConsecutiveErrors ?? 3,
    onFailure: (reason) => failures.push(reason),
  })
  return { messages, failures, stop }
}

describe("pollJobStatus", () => {
  test("stops on a terminal status without reporting a failure", async () => {
    let calls = 0
    const { messages, failures } = runPoll(async () => {
      calls += 1
      return message(calls < 3 ? "running" : "succeeded")
    })

    await sleep(50)

    expect(messages.at(-1)?.status).toBe("succeeded")
    expect(failures).toEqual([])
    const settled = calls
    await sleep(20)
    expect(calls).toBe(settled) // no ticks after the terminal status
  })

  test("a 404 (JobGoneError) is terminal: fails once as 'gone' and stops", async () => {
    let calls = 0
    const { failures } = runPoll(async () => {
      calls += 1
      throw new JobGoneError()
    })

    await sleep(50)

    expect(failures).toEqual(["gone"])
    expect(calls).toBe(1) // no retry after a gone job
  })

  test("gives up as 'unreachable' after maxConsecutiveErrors failures", async () => {
    let calls = 0
    const { failures } = runPoll(
      async () => {
        calls += 1
        throw new Error("connection refused")
      },
      { maxConsecutiveErrors: 3 }
    )

    await sleep(100)

    expect(failures).toEqual(["unreachable"])
    expect(calls).toBe(3)
  })

  test("a successful fetch resets the consecutive-error count", async () => {
    // Alternate failure/success: the error count never reaches the cap of 2.
    let calls = 0
    const { failures, messages, stop } = runPoll(
      async () => {
        calls += 1
        if (calls % 2 === 1) throw new Error("blip")
        return message("running")
      },
      { maxConsecutiveErrors: 2 }
    )

    await sleep(60)
    stop()

    expect(failures).toEqual([])
    expect(messages.length).toBeGreaterThan(1)
  })

  test("gives up as 'timeout' once the overall deadline elapses", async () => {
    const { failures } = runPoll(async () => message("running"), {
      deadlineMs: 15,
    })

    await sleep(80)

    expect(failures).toEqual(["timeout"])
  })

  test("the returned stop() halts polling and suppresses onFailure", async () => {
    let calls = 0
    const { failures, stop } = runPoll(async () => {
      calls += 1
      return message("running")
    })

    await sleep(20)
    stop()
    const settled = calls
    await sleep(20)

    expect(calls).toBe(settled)
    expect(failures).toEqual([])
  })
})
