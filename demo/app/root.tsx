import "./app.css"

import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration
} from "react-router"
import { TopNav, TopNavHeading, TopNavItem } from "@astryxdesign/core/TopNav"
import { LayerProvider } from "@astryxdesign/core/Layer"
import { Theme } from "@astryxdesign/core"
import NavHeaderIcon from "@/components/logo/app-logo"


import { AppShell } from "@astryxdesign/core/AppShell"
import { NavIcon } from "@astryxdesign/core"
import { CorporaTheme } from "@/utils/theme.ts"

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/corpus/upload", label: "Upload", end: false },
  { to: "/corpus/convert", label: "Convert", end: false },
  { to: "./logs", label: "Logs", end: true }
]

// Global document shell — everything renders inside this.
export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
    <head>
      <meta charSet="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <link rel="icon" href="data:image/x-icon;base64,AA" />
      <Meta />
      <Links />
      <title>Corpora</title>
    </head>
    <body>
    <LayerProvider>
      <AppShellWrapper>{children}</AppShellWrapper>
    </LayerProvider>
    <ScrollRestoration />
    <Scripts />

    </body>
    </html>
  )
}

const AppShellWrapper = ({ children }: { children: React.ReactNode }) => {
  return (
    <AppShell
      height="fill"
      contentPadding={10}
      topNav={
        <TopNav
          label="Main navigation"
          className="electrobun-webkit-app-region-drag"
          heading={
            <TopNavHeading
              heading="Corpora"
              logo={
                <NavIcon className="bg-transparent!" icon={<NavHeaderIcon className="fill-amber-400" />} />
              }
            />
          }
          startContent={
            NAV.map((navItem) => (
              <TopNavItem key={navItem.label} label={navItem.label} href={navItem.to} />
            ))
          }
        />
      }>
      {children}
    </AppShell>
  )
}

// Global UI (nav) lives in the root per framework-mode conventions.
export default function App() {
  return (
    <Theme theme={CorporaTheme}>
      <Outlet />
    </Theme>
  )
}
