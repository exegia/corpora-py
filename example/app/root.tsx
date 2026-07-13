import "~/app.css"
import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  useNavigate,
  isRouteErrorResponse,
} from "react-router"
import NavHeaderIcon from "~/components/logo"
import { ThemeProvider } from "~/components/theme-provider"
import { NAV } from "~/lib/constant"

import type { Route } from "./+types/root"
import type { ReactNode } from "react"

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

function Header() {
  const navigate = useNavigate()
  return (
    <header className="sticky top-0 z-50 border-b bg-white/80 backdrop-blur supports-backdrop-filter:bg-white/60 dark:bg-neutral-900/60">
      <div className="container mx-auto flex h-14 items-center justify-between gap-4 px-4">
        <button
          className="flex cursor-pointer items-center gap-2"
          onClick={() => navigate(NAV[0].to)}
        >
          <NavHeaderIcon className="h-5 w-5 fill-amber-400" />
          <span className="text-sm font-semibold">Corpora</span>
        </button>
        <nav className="flex items-center gap-1">
          {NAV.map((item) => (
            <button
              key={item.label}
              onClick={() => navigate(item.to)}
              className="cursor-pointer rounded-md px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-800"
            >
              {item.label}
            </button>
          ))}
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
        <link rel="icon" href="favicon.ico" />
        <Meta />
        <Links />
        <title>Corpora | Example</title>
      </head>
      <body className="min-h-svh bg-background text-foreground">
        <Header />
        <main className="container mx-auto px-4 py-6">{children}</main>
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  )
}

export default function App() {
  return (
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <Outlet />
    </ThemeProvider>
  )
}
