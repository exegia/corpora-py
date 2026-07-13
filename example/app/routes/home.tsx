import { useNavigate } from "react-router"
import { MENU_ITEMS } from "~/lib/constant"
import { Uploading } from "undraw-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "~/components/ui/card"
import { Button } from "~/components/ui/button"

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

function MenuCard({ item, size }: { item: typeof MENU_ITEMS[number]; size: "primary" | "secondary" }) {
  const Illustration = item.illustration ?? Uploading
  const isPrimary = size === "primary"
  const navigate = useNavigate()

  return (
    <Card
      className="h-full cursor-pointer hover:mix-blend-plus-lighter border-2 border-neutral-200 dark:border-neutral-800"
      onClick={() => navigate(item.to)}>
      <CardContent>
        <div className={isPrimary ? "mb-8 mt-4 p-4" : "mb-4 mt-2 p-2 w-full justify-center"}>
          {item.illustration && <Illustration viewBox="0 0 200 120" />}
        </div>
        <CardTitle className={isPrimary ? "text-2xl" : "text-lg"}>{item.label}</CardTitle>
        <CardDescription>{item.description}</CardDescription>
      </CardContent>
      <CardFooter>
        <Button variant="link" className="cursor-pointer">
          Open →
        </Button>
      </CardFooter>
    </Card>
  )
}
