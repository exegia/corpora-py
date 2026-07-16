import "~/app.css"
import type { FC, ReactNode, SVGProps } from "react"
import { useEffect } from "react"
import {
  isRouteErrorResponse,
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  useLocation,
  useNavigate,
} from "react-router"
import { Moon, Sun } from "lucide-react"
import NavHeaderIcon from "~/components/logo"
import { ThemeProvider, useTheme } from "~/components/theme-provider"
import { bindCues } from "~/lib/cue"
import { MENU_ITEMS } from "~/lib/constant"

import type { Route } from "./+types/root"
import { cn } from "~/lib/utils"

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  let message = "Oops!"
  let details = "An unexpected error occurred."
  let stack: string | undefined

  if (isRouteErrorResponse(error)) {
    message = error.status === 404 ? "404" : "Error"
    details =
      error.status === 404
        ? "The requested page could not be found."
        : error.statusText || details
  } else if (import.meta.env.DEV && error && error instanceof Error) {
    details = error.message
    stack = error.stack
  }

  return (
    <main className="container mx-auto p-4 pt-16">
      <h1>{message}</h1>
      <p>{details}</p>
      {stack && (
        <pre className="w-full overflow-x-auto p-4">
          <code>{stack}</code>
        </pre>
      )}
    </main>
  )
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches)
  return (
    <button
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="cursor-pointer rounded-md p-2 hover:bg-neutral-100 dark:hover:bg-neutral-800"
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  )
}

const MenuIconComponent = ({
  icon,
}: {
  icon: FC<SVGProps<SVGSVGElement>> | undefined
}) => {
  if (!icon) return
  const Component = icon
  return <Component className="h-4 w-auto" />
}

function Header() {
  const navigate = useNavigate()
  const active = useLocation()
  return (
    <header className="sticky top-0 z-50 border-b bg-white/80 backdrop-blur supports-backdrop-filter:bg-white/60 dark:bg-neutral-900/60">
      <div className="container mx-auto flex h-14 items-center justify-between gap-4 px-4">
        <button
          className="flex cursor-pointer items-center gap-2"
          onClick={() => navigate(MENU_ITEMS[0].to)}
        >
          <NavHeaderIcon className="h-6 w-6 fill-amber-400" />
          <span className="font-serif text-base font-semibold">Corpora</span>
        </button>
        <nav className="anim flex items-center gap-1">
          {MENU_ITEMS.map((item) => (
            <button
              key={item.label}
              onClick={() => navigate(item.to)}
              className={cn(
                "bg-opacity-0 flex cursor-pointer flex-row items-center gap-1.5 rounded-md px-3 py-1.5 text-sm" +
                  " animate-delay-100" +
                  " animate-duration-slow" +
                  " hover:bg-neutral-100" +
                  " transition-colors dark:hover:bg-neutral-800",
                active.pathname == item.to
                  ? "bg-amber-300 font-medium text-neutral-700 hover:bg-amber-400!"
                  : ""
              )}
            >
              {item.icon && <MenuIconComponent icon={item.icon} />}
              {item.label}
            </button>
          ))}
          <ThemeToggle />
        </nav>
      </div>
    </header>
  )
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
        <Meta />
        <Links />
        <title>Corpora | Example</title>
      </head>
      <body className="min-h-svh bg-neutral-200 text-foreground dark:bg-neutral-950">
        {/* The provider lives here (not in App) so the Header's ThemeToggle is
        inside it — Layout renders above App in the framework-mode tree. */}
        <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
          <Header />
          <main className="container mx-auto px-4 py-6">{children}</main>
        </ThemeProvider>
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  )
}

export default function App() {
  // Wire the declarative `data-cuelume-*` interaction sounds once, on the
  // client. Idempotent and SSR-safe (see `bindCues`).
  useEffect(() => {
    bindCues()
  }, [])

  return <Outlet />
}
