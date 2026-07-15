import { useNavigate } from "react-router"
import { MENU_ITEMS } from "~/lib/constant"
import { Uploading } from "undraw-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardTitle,
} from "~/components/ui/card"
import { Button } from "~/components/ui/button"

export function meta() {
  return [
    { title: "Explore | Corpora", description: "Explore Uploaded datasets" },
    { tagName: "link", rel: "icon", href: "/favicon.ico" },
  ]
}

export default function Explore() {
  return <div></div>
}
