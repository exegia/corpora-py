import { Link, useNavigate } from "react-router"
import { SettingsIcon } from "lucide-react"
import { MENU_ITEMS } from "~/lib/constant"
import { Uploading } from "undraw-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardTitle,
} from "~/components/ui/card"

export function meta() {
  return [{ title: "Home | Corpora" }]
}

/** The guided tour rendered below the menu cards: one step per screen of the
 * upload → explore → read → chat flow, each illustrated with a real
 * screenshot (captured from this app with the SBLGNT demo corpus). Laid out
 * as a symmetric bento grid on large screens — `span` is the lg column span
 * (of 5), alternating wide/narrow per row: 3+2, 2+3, 3+2. */
const HOW_TO_STEPS = [
  {
    title: "Upload a source document",
    screenshot: "/screenshots/upload.png",
    span: "lg:col-span-3",
    alt: "The Upload page with a GitHub repository field and a drag-and-drop zone listing the accepted file types",
    body: (
      <>
        Head to <strong>Upload</strong> and either paste the URL of a public
        GitHub repository that contains a Text-Fabric corpus, or drag and drop
        a file — <code>.epub</code>, <code>.html</code>, <code>.xml</code>/
        <code>.tei</code>, <code>.pdf</code>, <code>.txt</code>, or a{" "}
        <code>.zip</code> of an existing Text-Fabric dataset. Conversion starts
        as soon as the file lands. (Want something to try? Grab{" "}
        <a
          href="/SBLGNT.zip"
          download
          className="underline underline-offset-2 hover:text-foreground"
        >
          the SBLGNT demo corpus
        </a>
        .)
      </>
    ),
  },
  {
    title: "Watch it become a .corpus archive",
    screenshot: "/screenshots/convert-done.png",
    span: "lg:col-span-2",
    alt: "A finished conversion showing completed processing stages, live logs, and a Download button for the .corpus archive",
    body: (
      <>
        Each processing stage reports its progress next to a live log console:
        the file is validated, parsed into a Text-Fabric dataset, and packaged
        as a Context-Fabric <code>.corpus</code> archive. When it finishes you
        can download the archive, publish it to the Hugging Face Hub, or
        convert another file.
      </>
    ),
  },
  {
    title: "Explore published corpora",
    screenshot: "/screenshots/explore.png",
    span: "lg:col-span-2",
    alt: "The Explore page listing a published corpus with Download and Open on Hugging Face actions",
    body: (
      <>
        <strong>Explore</strong> lists every <code>.corpus</code> archive
        published to the configured Hugging Face Hub storage. Search the
        library, download an archive, or select one and open it to see its
        manifest metadata and browse its contents.
      </>
    ),
  },
  {
    title: "Read it in the workspace",
    screenshot: "/screenshots/workspace.png",
    span: "lg:col-span-3",
    alt: "The corpus viewer showing paginated Greek New Testament passages beside the AI assistant panel",
    body: (
      <>
        A corpus opens into a split workspace: a paginated reader with
        section-by-section navigation on the left, and the AI assistant on the
        right. Attach passages to the conversation, ask the assistant to audit
        nodes over MCP, or use the premade prompts to fix sections, text, and
        clauses. It answers on a free demo model out of the box — add your own
        Anthropic API key in <strong>Settings</strong> to switch to Claude.
      </>
    ),
  },
  {
    title: "Chat with a loaded corpus",
    screenshot: "/screenshots/chat.png",
    span: "lg:col-span-3",
    alt: "The Chat page prompting to select a published corpus before the conversation unlocks",
    body: (
      <>
        <strong>Chat</strong> goes corpus-first: pick a published archive, let
        it load into the MCP server, and the conversation unlocks with the
        assistant introducing the corpus. From there, ask questions and explore
        the text conversationally.
      </>
    ),
  },
]

export default function Home() {
  const [, ...rest] = MENU_ITEMS

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">Welcome to Corpora</h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Convert, browse, and chat with your Text-Fabric corpora.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        {rest
          .filter((item) => item.to !== "/settings")
          .map((item) => (
            <MenuCard key={item.to} item={item} size="primary" />
          ))}
      </div>

      <section
        aria-labelledby="how-it-works"
        className="mt-10 flex flex-col gap-10"
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="relative border border-neutral-200 px-6 py-3 dark:border-neutral-800">
            <CornerAccents />
            <h2 id="how-it-works" className="text-2xl font-bold md:text-3xl">
              How it works
            </h2>
          </div>
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            From source document to conversational corpus in five steps.
          </p>
        </div>

        <ol className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          {HOW_TO_STEPS.map((step, index) => (
            <li
              key={step.title}
              className={`flex flex-col overflow-hidden rounded-2xl border border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900 ${step.span}`}
            >
              <div className="p-6 pb-0">
                <div className="flex items-center gap-2.5">
                  <span
                    aria-hidden="true"
                    className="flex size-6 shrink-0 items-center justify-center rounded-full bg-amber-400 text-xs font-semibold text-neutral-900"
                  >
                    {index + 1}
                  </span>
                  <h3 className="text-base font-semibold">{step.title}</h3>
                </div>
                <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">
                  {step.body}
                </p>
              </div>
              <div className="relative mt-6 h-60 grow">
                <img
                  src={step.screenshot}
                  alt={step.alt}
                  loading="lazy"
                  className="absolute top-0 left-6 w-full rounded-tl-lg border border-neutral-200 object-cover object-left-top shadow-xl dark:border-neutral-700"
                />
              </div>
            </li>
          ))}

          <li className="flex flex-col justify-center gap-3 rounded-2xl border border-neutral-200 bg-neutral-50 p-6 lg:col-span-2 dark:border-neutral-800 dark:bg-neutral-900">
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="flex size-6 shrink-0 items-center justify-center rounded-full bg-amber-400 text-neutral-900"
              >
                <SettingsIcon className="size-3.5" />
              </span>
              <h3 className="text-base font-semibold">Bring your own keys</h3>
            </div>
            <p className="text-sm text-neutral-500 dark:text-neutral-400">
              <Link
                to="/settings"
                className="underline underline-offset-2 hover:text-foreground"
              >
                Settings
              </Link>{" "}
              keeps your API keys in the browser&apos;s local storage: a
              Hugging Face token unlocks publishing to your own Hub storage,
              and an Anthropic key upgrades the assistant from the free demo
              model to Claude.
            </p>
          </li>
        </ol>
      </section>
    </div>
  )
}

/** The four little squares on the corners of the "How it works" title box —
 * the same accent the Aceternity symmetric bento grid uses on its header. */
function CornerAccents() {
  return (
    <>
      {[
        "-top-1 -left-1",
        "-top-1 -right-1",
        "-bottom-1 -left-1",
        "-bottom-1 -right-1",
      ].map((position) => (
        <span
          key={position}
          aria-hidden="true"
          className={`absolute size-2 border border-neutral-300 bg-background dark:border-neutral-700 ${position}`}
        />
      ))}
    </>
  )
}

function MenuCard({
  item,
  size,
}: {
  item: (typeof MENU_ITEMS)[number]
  size: "primary" | "secondary"
}) {
  const Illustration = item.illustration ?? Uploading
  const isPrimary = size === "primary"
  const navigate = useNavigate()

  return (
    <Card
      className="h-full transform cursor-pointer rounded-3xl border border-neutral-100 shadow shadow-neutral-300 transition-all hover:-translate-y-1 hover:bg-neutral-100 hover:shadow-2xl dark:border-neutral-800 dark:shadow-black dark:hover:bg-neutral-950"
      onClick={() => navigate(item.to)}
    >
      <CardContent>
        <div
          className={
            isPrimary ? "mt-4 mb-8 p-4" : "mt-2 mb-4 w-full justify-center p-2"
          }
        >
          {item.illustration && <Illustration viewBox="0 0 200 120" />}
        </div>
        <CardTitle className={isPrimary ? "text-2xl" : "text-lg"}>
          {item.label}
        </CardTitle>
        <CardDescription>{item.description}</CardDescription>
      </CardContent>
    </Card>
  )
}
