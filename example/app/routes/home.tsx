import { useNavigate } from "react-router"
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
        {rest.map((item) => (
          <MenuCard key={item.to} item={item} size="primary" />
        ))}
      </div>
    </div>
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
      className="h-full transform cursor-pointer rounded-2xl border border-neutral-100 shadow shadow-neutral-300 transition-all hover:-translate-y-1 hover:bg-neutral-100 hover:shadow-2xl dark:border-neutral-800 dark:hover:bg-neutral-950"
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
