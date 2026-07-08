import { useNavigate } from "react-router"
import { MENU_ITEMS } from "~/lib/constant"
import { Uploading } from "undraw-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "~/components/ui/card"
import { Button } from "~/components/ui/button"

export function meta() {
  return [{ title: "Home | Corpora" }]
}


export default function Home() {
  const [, primary, ...rest] = MENU_ITEMS

  return (
    <div className="flex w-full flex-col gap-6">
      <div>
        <h2 className="text-2xl font-semibold">Welcome to Corpora</h2>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Convert, browse, and chat with your Text-Fabric corpora.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <div className="md:col-span-2 md:row-span-2">
          <MenuCard item={primary} size="primary" />
        </div>
        {rest.map((item) => (
          <MenuCard key={item.to} item={item} size="secondary" />
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
    <Card className="h-full cursor-pointer" onClick={() => navigate(item.to)}>
      <CardContent>
        <div className={isPrimary ? "h-67" : "h-24"}>
          {item.illustration && <Illustration color="orange" style={{ color: "orange" }} />}
        </div>
        <CardTitle className={isPrimary ? "text-2xl" : "text-lg"}>{item.label}</CardTitle>
        <CardDescription>{item.description}</CardDescription>
      </CardContent>
      <CardFooter>
        <Button variant="link">
          Open →
        </Button>
      </CardFooter>
    </Card>
  )
}
